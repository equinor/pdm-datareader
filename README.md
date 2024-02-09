# PDM Tools

<p align="center">
<img src="pdm-tools.svg" alt="pdm-tools logo" width="50%">
</p>

This is a simple tool package for querying data from 
[Production Data Mart](https://wiki.equinor.com/wiki/index.php/Production_Data_Mart) without having to re-authenticate every time. 

Pull requests, feature requests and issues are welcome to be filed through the 
[GitHub Project Repository](https://github.com/equinor/pdm-tools) or as a ServiceNow ticket 
directed to Production Data Mart.

## Install
1. From the python environment you want to install the package in, run:  
    ```pip install git+https://github.com/equinor/pdm-tools.git```  
2. Install [ODBC Driver for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) (v18 and v17 currently supported).  
This driver is bundled with the [Microsoft SQL Client](https://accessit.equinor.com/Search/Search?term=MICROSOFT+SQL+CLIENT) package in AccessIT.
3. For MacOS users it is recommended to also install unixodbc, see [https://pypi.org/project/pyodbc/](https://pypi.org/project/pyodbc/) for current instructions.

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

