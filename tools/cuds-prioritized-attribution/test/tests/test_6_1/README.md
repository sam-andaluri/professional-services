Testcase: 6_1
Criteria : More purchases than CUDs - provided folders only
========

Folder-1 --> Project-1
Folder-2 --> Project-2
Folder-3 --> Project-3

|----COMMITMENTS--|----------BILLING EXPORT-----------------|------------------BILLING OUTPUT------------------|
|     Purchases   |     Usage    |BA level|BA level|BA level| Expected CUD  |  Expected SUD    |Expected COST  |
| Projects |Amount|              |  CUD   |  SUD   | COST   |  allocation   |   allocation     | allocation    |
| ---------|----- |--------------|-----------------|--------|---------------|------------------|---------------|
|T1:Folder-1:100  |Project-1: 50 |   30   |  10    |  100   | Project-1: 15 | Project-1: 1.84  |Project-1:66.66|
|                 |Project-2:100 |                          | Project-2: 15 | Project-2: 4.47  |Project-2:33.33|
|T2:Folder-2:50   |Project-3: 70 |                          | Project-3: 0  | Project-3: 3.68  |Project-3: 0   |
|--------------------------------------------------------------------------------------------------------------|
