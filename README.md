# PDM Tools

<p align="center">
<img src="pdm-tools.svg" alt="pdm-tools logo" width="50%">
</p>

[![Runs on Windows](https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white)
[![Runs on MacOS](https://img.shields.io/badge/mac%20os-000000?style=for-the-badge&logo=apple&logoColor=white)](https://img.shields.io/badge/mac%20os-000000?style=for-the-badge&logo=apple&logoColor=white)
[![Runs on RHEL7](https://img.shields.io/badge/Red%20Hat-EE0000?style=for-the-badge&logo=redhat&logoColor=white)](https://img.shields.io/badge/Red%20Hat-EE0000?style=for-the-badge&logo=redhat&logoColor=white)
[![SCM Compliance](https://scm-compliance-api.radix.equinor.com/repos/equinor/neqsim/badge)](https://scm-compliance-api.radix.equinor.com/repos/equinor/neqsim/badge)

This is a simple python package for querying [Production Data Mart](https://wiki.equinor.com/wiki/index.php/Production_Data_Mart) tables using SQL. The package handles authentication for end users. It must be run from Equinor managed environments.

Pull requests, feature requests and issues are welcomed using the [GitHub Project Repository](https://github.com/equinor/pdm-tools) or as a ServiceNow ticket directed to Production Data Mart.

## Install
1. Ensure that [ODBC Driver for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) is installed. Currently supports both v18 and v17.  
This driver is bundled with the [Microsoft SQL Client](https://accessit.equinor.com/Search/Search?term=MICROSOFT+SQL+CLIENT) package in AccessIT, and should be pre installed on linux environments, on MacOS it can be installed using brew.  
2. For MacOS users it is also recommended to install unixodbc. See [https://pypi.org/project/pyodbc/](https://pypi.org/project/pyodbc/) for current instructions.
3. Finally install the latest version of the python package using:  
    ```pip install git+https://github.com/equinor/pdm-tools.git```  

## Usage
See [examples/demo.py](examples/demo.py) or try the code below that queries PDM and retrieves data:  
```
import datetime as dt

from pdm_tools import tools

sql = 'SELECT TOP(1) * FROM PDMVW.WELL_PROD_DAY'
df = tools.query(sql)
print(df)

# Use parameter bindings to avoid SQL injection issues.
sql = "SELECT top(100) * FROM PDMVW.WELL_PROD_DAY WHERE COUNTRY = :countrycode AND PROD_DAY = :startdate"
df = tools.query(sql, params={'countrycode': 'NO',
                 'startdate': dt.datetime(2022, 1, 1)})
print(df)
```
   
## Legacy
If you wish to use an older version of this package, this can be done by passing a parameter with the pip-command, e.g.: <br>
    ````
    pip install git+https://github.com/equinor/pdm-tools.git@v1.0
    ````

