# PDM Tools

This is a simple tool package for querying data from [Production Data Mart](https://wiki.equinor.com/wiki/index.php/Production_Data_Mart) without having to re-authenticate every time. <br>
**Author**: [Chinazor Allen](mailto:chial@equinor.com)

## Usage
1. From the python environment you want to install the package in, run:<br>
    ```pip install git+https://github.com/equinor/pdm-tools.git```<br>
2. To query PDM and retrieve data:<br>
    ```
    import datetime as dt

    from pdm_tools import tools

    sql = 'SELECT TOP(1) * FROM PDMVW.WELL_PROD_DAY'
    df = tools.query(sql)
    print(df)

    sql = "SELECT top(100) * FROM PDMVW.WELL_PROD_DAY WHERE COUNTRY = ? AND WELL_V_END_DATE > ? and WELL_V_END_DATE < ?"
    df = tools.query(sql, params=["NO", dt.datetime(
        2022, 5, 10), dt.datetime(2022, 5, 15)])
    print(df)

    ```

