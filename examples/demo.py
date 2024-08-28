import datetime as dt

from pdm_tools import tools

sql = "SELECT TOP(1) * FROM PDMVW.WELL_PROD_DAY"
df = tools.query(sql)
print(df)

# Example with parameter bindings to avoid SQL injection issues (recommended)
sql = "SELECT top(10) * FROM PDMVW.WELL_PROD_DAY WHERE COUNTRY = :countrycode AND PROD_DAY = :startdate"
df = tools.query(
    sql, params={"countrycode": "NO", "startdate": dt.datetime(2022, 1, 1)}
)
print(df)


# optionally set your own token using
tools.reset_engine()
str_tok = tools.get_token()
tools.set_token(str_tok)
df = tools.query(
    sql, params={"countrycode": "NO", "startdate": dt.datetime(2022, 1, 1)}
)
print(df)
