import datetime as dt

from pdm_tools import tools

sql = 'SELECT TOP(1) * FROM PDMVW.WELL_PROD_DAY'
df = tools.query(sql)
print(df)

sql = "SELECT top(100) * FROM PDMVW.WELL_PROD_DAY WHERE COUNTRY = ? AND WELL_V_END_DATE > ? and WELL_V_END_DATE < ?"
df = tools.query(sql, params=["NO", dt.datetime(
    2022, 5, 10), dt.datetime(2022, 5, 15)])
print(df)

sql = 'SELECT TOP(1) * FROM PDMVW.WELL_PROD_DAY'
df = tools.query(sql)
print(df)
