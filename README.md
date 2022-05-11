# PDM Tools

This is a simple tool package for querying data from [Production Data Mart](https://wiki.equinor.com/wiki/index.php/Production_Data_Mart) without having to re-authenticate every time. <br>
**Author**: [Chinazor Allen](mailto:chial@equinor.com)

## Usage
1. Git clone this repository
2. Navigate to the local folder cloned
3. From the python environment you want to install the package to, run:<br>
    ```pip install .```
4. To import the installed module in your python file(s):<br>
    ```from pdm_tools import tools```<br>
5. To query PDM and retrieve data:<br>
    ```sql = 'SELECT TOP(1) * FROM PDMVW.WELL_PROD_DAY```<br>
    ```df = tools.query('shortname', sql)```

