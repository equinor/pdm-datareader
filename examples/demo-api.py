"""Read a PDM view through the API."""

import datetime as dt

from pdm_datareader import read_api_view, Range

df = read_api_view(
    "WellProdDay",
    filters={
        "COUNTRY": "NO",
        "PROD_DAY": Range(dt.date(2024, 1, 1), dt.date(2024, 1, 31)),
    },
    columns=["PROD_DAY", "WELL_UWI", "ALLOC_OIL_VOL_SM3"],
    order_by="PROD_DAY DESC, WELL_UWI",
)
print(df)
