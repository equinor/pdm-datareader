import datetime as dt

from pdm_tools import tools

sql = "SELECT TOP(1) * FROM PDMVW.WELL_PROD_DAY"
df = tools.query(sql)
print(df)

# Use parameter bindings to avoid SQL injection issues.
sql = "SELECT top(100) * FROM PDMVW.WELL_PROD_DAY WHERE COUNTRY = :countrycode AND PROD_DAY = :startdate"
df = tools.query(
    sql, params={"countrycode": "NO", "startdate": dt.datetime(2022, 1, 1)}
)
print(df)
