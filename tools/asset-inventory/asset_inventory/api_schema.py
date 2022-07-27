#!/usr/bin/env python
#
# Copyright 2019 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Generates BigQuery schema from API discovery documents."""

import re

from asset_inventory import bigquery_schema
import requests


class APISchema(object):
    """Convert a CAI asset type to a BigQuery table schema.

    When import_pipeline uses a group_by of ASSET_TYPE or ASSET_TYPE_VERSION
    use a BigQuery schema generated from API discovery documents. This
    gives us all the type, names and description of an asset type property.
    Will union all API versions into a single schema.
    """

    _discovery_document_cache = dict()
    _schema_cache = {}

    @classmethod
    def _get_discovery_document(cls, dd_url):
        """Retreive and cache a discovery document."""
        if dd_url in cls._discovery_document_cache:
            return cls._discovery_document_cache[dd_url]
        discovery_document = None
        # Ignore discovery document urls that aren't urls.
        if dd_url and dd_url.startswith('http'):
            response = requests.get(dd_url)
            if response.status_code == 200:
                try:
                    discovery_document = response.json()
                except ValueError:
                    pass
        cls._discovery_document_cache[dd_url] = discovery_document
        return discovery_document

    @classmethod
    def _get_api_name_for_discovery_document_url(cls, dd_url):
        """Get API name from discovery document url.

        Args:
          dd_url: Discovery document url.
        Returns:
          API name if can be found, None otherwise.
        """
        apiary_match = re.match(r'https://(?:[^/]+)/discovery/v1/apis/([^/]+)',
                                dd_url)
        if apiary_match:
            return apiary_match.group(1)
        one_match = re.match(r'https://([^.]+).googleapis.com/\$discovery/rest',
                             dd_url)
        if one_match:
            return one_match.group(1)
        return None

    @classmethod
    def _get_discovery_document_versions(cls, dd_url):
        """Return all verisons of the APIs discovery documents.

        Args:
          dd_url: the url of the asset's discovery document.
        Returns:
           list of discovery document json objects.
        """
        # calculate all the discovery documents from the url.
        discovery_documents = []
        api_name = cls._get_api_name_for_discovery_document_url(dd_url)
        dd = cls._get_discovery_document(dd_url)
        # add the discovery document to return value
        discovery_documents += [dd] if dd else []
        # and discovery documents from other versions of the same API.
        all_discovery_docs = cls._get_discovery_document(
            'https://content.googleapis.com/discovery/v1/apis')
        for discovery_doc in all_discovery_docs['items']:
            dru = discovery_doc['discoveryRestUrl']
            if (api_name == discovery_doc['name'] and dru != dd_url):
                dd = cls._get_discovery_document(dru)
                discovery_documents += [dd] if dd else []
        return discovery_documents

    @classmethod
    def _get_schema_for_resource(cls, discovery_documents, resource_name):
        """Translate API discovery documents to a BigQuery schema."""
        schemas = [
            cls._translate_resource_to_schema(resource_name, document)
            for document in discovery_documents
        ]
        merged_schema = bigquery_schema.merge_schemas(schemas)
        return merged_schema

    @classmethod
    def _get_bigquery_type_for_property(cls, property_value, resources):
        """Map API type to a BigQuery type."""
        # default type
        bigquery_type = 'STRING'
        property_type = property_value.get('type', None)
        # nested record.
        if property_type == 'object' or 'properties' in property_value:
            bigquery_type = 'RECORD'
        # repeated, recurse into element type.
        elif property_type == 'array':
            return cls._get_bigquery_type_for_property(
                property_value['items'],
                resources)
        if property_type in ('number', 'integer'):
            bigquery_type = 'NUMERIC'
        elif property_type == 'boolean':
            bigquery_type = 'BOOL'
        # type reference.
        elif '$ref' in property_value:
            property_resource_name = cls._ref_resource_name(property_value)
            if property_resource_name:
                return cls._get_bigquery_type_for_property(
                    resources[property_resource_name],
                    resources)
            return bigquery_type
        return bigquery_type

    @classmethod
    def _ref_resource_name(cls, property_value):
        ref_name = property_value.get('$ref', None)
        # strip the '#/definitions/' prefix if present.
        if ref_name and ref_name.startswith('#/definitions/'):
            return ref_name[len('#/definitions/'):]
        return ref_name

    @classmethod
    def _get_properties_map_field_list(cls, property_name, property_value,
                                       resources, seen_resources):
        """Return the fields of the `RECORD` property.

        Args:
            property_name: name of API property
            property_value: value of the API property.
            resources: dict of all other resources that might be referenced by
            the API schema through reference types ($ref values).
            seen_resources: dict of types we have processed to prevent endless
            cycles.
        Returns:
            BigQuery fields dict list or None if the field should be skipped.
        """
        # found a record type, this is a recursive exit condition.
        if 'properties' in property_value:
            return cls._properties_map_to_field_list(
                property_value['properties'], resources, seen_resources)
        property_resource_name = cls._ref_resource_name(property_value)
        # get fields of the reference type.
        if property_resource_name:
            # not handling recursive fields.
            if property_resource_name in seen_resources:
                return None
            # rack prior types to not recurse forever.
            seen_resources[property_resource_name] = True
            return_value = cls._get_properties_map_field_list(
                property_resource_name, resources[property_resource_name],
                resources, seen_resources)
            del seen_resources[property_resource_name]
            return return_value
        # get fields of item type.
        if 'items' in property_value:
            return cls._get_properties_map_field_list(
                property_name, property_value['items'],
                resources, seen_resources)
        # convert additionalProperties fields to a dict
        # of name value pairs for a more regular schema.
        if 'additionalProperties' in property_value:
            fields = [{'name': 'name',
                       'field_type': 'STRING',
                       'description': 'additionalProperties name',
                       'mode': 'NULLABLE'}]
            fields.append(
                cls._property_to_field(
                    'value',
                    property_value['additionalProperties'],
                    resources, seen_resources))
            return fields
        # unknown property type.
        return None

    @classmethod
    def _property_to_field(cls, property_name, property_value,
                           resources, seen_resources):
        """Convert api property to BigQuery field.

        Args:
            property_name: name of API property
            property_value: value of the API property.
            resources: dict of all other resources that might be referenced by
            the API schema through reference types ($ref values).
            seen_resources: dict of types we have processed to prevent endless
        Returns:
            BigQuery field or None if the field should be skipped.
        """
        field = {'name': property_name}
        property_type = property_value.get('type', None)
        bigquery_type = cls._get_bigquery_type_for_property(
            property_value, resources)
        field['field_type'] = bigquery_type
        if 'description' in property_value:
            field['description'] = property_value['description'][:1024]

        # array fields are BigQuery repeated fields, and convert
        # additionalProperties to repeated lists of key value pairs.
        if (property_type == 'array' or
            'additionalProperties' in property_value):
            field['mode'] = 'REPEATED'
        else:
            field['mode'] = 'NULLABLE'

        if bigquery_type == 'RECORD':
            fields_list = cls._get_properties_map_field_list(
                property_name, property_value, resources, seen_resources)
            if not fields_list:
                return None
            field['fields'] = fields_list
        return field

    @classmethod
    def _properties_map_to_field_list(cls, properties_map, resources,
                                      seen_resources):
        """Convert API resource properties to BigQuery schema.

        Args:
            properties_map: dict of properties from the API schema document we
            are convering into a BigQuery field list.
            resources: dict of all other resources that might be referenced by
            the API schema through reference types ($ref values).
            seen_resources: dict of types we have processed to prevent endless
            cycles.
        Returns:
            BigQuery fields dict list.
        """
        fields = []
        for property_name, property_value in properties_map.items():
            field = cls._property_to_field(property_name, property_value,
                                           resources, seen_resources)
            if field is not None:
                fields.append(field)
        return fields

    @classmethod
    def _get_cache_key(cls, resource_name, document):
        if 'id' in document:
            return '{}.{}'.format(document['id'], resource_name)
        if 'info' in document:
            info = document['info']
            return '{}.{}.{}'.format(info['title'],
                                     info['version'],
                                     resource_name)
        return resource_name

    @classmethod
    def _get_document_resources(cls, document):
        if document.get('schemas'):
            return document['schemas']
        return document.get('definitions', [])

    @classmethod
    def _translate_resource_to_schema(cls, resource_name, document):
        """Expands the $ref properties of a reosurce definition."""
        cache_key = cls._get_cache_key(resource_name, document)
        if cache_key in cls._schema_cache:
            return cls._schema_cache[cache_key]
        resources = cls._get_document_resources(document)
        field_list = []
        if resource_name in resources:
            resource = resources[resource_name]
            properties_map = resource['properties']
            field_list = cls._properties_map_to_field_list(
                properties_map, resources, {resource_name: True})
        cls._schema_cache[cache_key] = field_list
        return field_list

    @classmethod
    def _add_asset_export_fields(cls,
                                 schema,
                                 include_resource=True,
                                 include_iam_policy=True):
        """Add the fields that the asset export adds to each resource.

        Args:
            schema: list of `google.cloud.bigquery.SchemaField` like dict
                     objects .
            include_resource: to include resource schema.
            include_iam_policy: to include iam policy schema.
        Returns:
            list of `google.cloud.bigquery.SchemaField` like dict objects.

        """
        asset_schema = [{
            'name': 'name',
            'field_type': 'STRING',
            'description': 'URL of the asset.',
            'mode': 'REQUIRED'
        }, {
            'name': 'asset_type',
            'field_type': 'STRING',
            'description': 'Asset name.',
            'mode': 'REQUIRED'
        }, {
            'name': 'timestamp',
            'field_type': 'TIMESTAMP',
            'description': 'Load time.',
            'mode': 'NULLABLE'
        }]
        if include_resource:
            resource_schema = list(schema)
            _, last_modified = bigquery_schema.get_field_by_name(
                resource_schema,
                'lastModifiedTime')
            if not last_modified:
                resource_schema.append({
                    'name': 'lastModifiedTime',
                    'field_type': 'STRING',
                    'mode': 'NULLABLE',
                    'description': 'Last time resource was changed.'
                })
            asset_schema.append({
                'name': 'resource',
                'field_type': 'RECORD',
                'description': 'Resource properties.',
                'mode': 'NULLABLE',
                'fields': [{
                    'name': 'version',
                    'field_type': 'STRING',
                    'description': 'Api version of resource.',
                    'mode': 'REQUIRED'
                }, {
                    'name': 'discovery_document_uri',
                    'field_type': 'STRING',
                    'description': 'Discovery document uri.',
                    'mode': 'REQUIRED'
                }, {
                    'name': 'parent',
                    'field_type': 'STRING',
                    'description': 'Parent resource.',
                    'mode': 'NULLABLE'
                }, {
                    'name': 'discovery_name',
                    'field_type': 'STRING',
                    'description': 'Name in discovery document.',
                    'mode': 'REQUIRED'
                }, {
                    'name': 'data',
                    'field_type': 'RECORD',
                    'description': 'Resource properties.',
                    'mode': 'NULLABLE',
                    'fields': resource_schema
                }]
            })
        if include_iam_policy:
            asset_schema.append({
                'name': 'iam_policy',
                'field_type': 'RECORD',
                'description': 'IAM Policy',
                'mode': 'NULLABLE',
                'fields': [{
                    'name': 'etag',
                    'field_type': 'STRING',
                    'description': 'Etag.',
                    'mode': 'NULLABLE'
                }, {
                    'name': 'audit_configs',
                    'field_type': 'RECORD',
                    'description': 'Logging of each type of permission.',
                    'mode': 'REPEATED',
                    'fields': [{
                        'name': 'service',
                        'field_type': 'STRING',
                        'description':
                            'Service that will be enabled for audit logging.',
                        'mode': 'NULLABLE'
                    }, {
                        'name': 'audit_log_configs',
                        'field_type': 'RECORD',
                        'description': 'Logging of each type of permission.',
                        'mode': 'REPEATED',
                        'fields': [{
                            'name': 'log_type',
                            'field_type': 'NUMERIC',
                            'mode': 'NULLABLE',
                            'description':
                            ('1: Admin reads. Example: CloudIAM getIamPolicy'
                             '2: Data writes. Example: CloudSQL Users create'
                             '3: Data reads. Example: CloudSQL Users list')
                        }]
                    }]
                }, {
                    'name': 'bindings',
                    'field_type': 'RECORD',
                    'mode': 'REPEATED',
                    'description': 'Bindings',
                    'fields': [{
                        'name': 'role',
                        'field_type': 'STRING',
                        'mode': 'NULLABLE',
                        'description': 'Assigned role.'
                    }, {
                        'name': 'members',
                        'field_type': 'STRING',
                        'mode': 'REPEATED',
                        'description': 'Principles assigned the role.'
                    }]
                }]
            })

        return asset_schema

    @classmethod
    def bigquery_schema_for_resource(cls, asset_type,
                                     resource_name,
                                     discovery_doc_url,
                                     include_resource,
                                     include_iam_policy):
        """Returns the BigQuery schema for the asset type.

        Args:
            asset_type: CAI asset type.
            resource_name: name of the resource.
            discovery_doc_url: URL of discovery document
            include_resource: if resource schema should be included.
            include_iam_policy: if IAM policy schema should be included.
        Returns:
            BigQuery schema.
        """
        cache_key = '{}.{}.{}'.format(asset_type, include_resource,
                                      include_iam_policy)
        if cache_key in cls._schema_cache:
            return cls._schema_cache[cache_key]
        # get the resource schema if we are including the resource
        # in the export.
        resource_schema = None
        if include_resource:
            discovery_documents = cls._get_discovery_document_versions(
                discovery_doc_url)
            resource_schema = cls._get_schema_for_resource(
                discovery_documents,
                resource_name)
        schema = cls._add_asset_export_fields(
            resource_schema, include_resource, include_iam_policy)
        cls._schema_cache[cache_key] = schema
        return schema
