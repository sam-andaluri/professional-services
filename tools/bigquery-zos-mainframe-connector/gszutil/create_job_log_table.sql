/*
 * Copyright 2022 Google LLC All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
CREATE TABLE IF NOT EXISTS `[PROJECT_ID].[DATASET_NAME].[TABLE_NAME]` (
  jobid string,
  jobdate string,
  jobtime string,
  jobname string,
  stepname string,
  procstepname string,
  symbols string,
  user string,
  script string,
  template string
)
PARTITION BY DATE(_PARTITIONTIME)
CLUSTER BY jobid
OPTIONS(
  description='mainframe job log',
  labels=[("bqmld", "zos")]
);
