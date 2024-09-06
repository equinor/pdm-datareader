import shutil
import pathlib

from pdm_datareader import query
from msal_bearer.BearerAuth import set_token_location


def replace_file(filename: str) -> str:
    dir_path = pathlib.Path(__file__).parent
    dest = dir_path.joinpath("tmp", "token_cache_invalid.bin")
    source = dir_path.joinpath(filename)
    dest.unlink(missing_ok=True)

    if not dest.parent.is_dir():
        dest.parent.mkdir()
    shutil.copyfile(src=source, dst=dest)

    return str(dest)


sql = "SELECT [FCTY_CODE] FROM [PDMVW].[FACILITY_MASTER] WHERE STID_CODE = 'JSV'"


def test_normal():
    df = query(sql)
    assert df["FCTY_CODE"][0] == "JSFC"


def test_handle_invalid_tokens():
    set_token_location(replace_file("token_cache_invalid_user.bin"))
    df = query(sql, verbose=True)
    assert df["FCTY_CODE"][0] == "JSFC"

    set_token_location(replace_file("token_cache_actually.txt"))
    df = query(sql, verbose=True)
    assert df["FCTY_CODE"][0] == "JSFC"

    set_token_location(replace_file("token_cache_invalid_filetype.bmp"))
    df = query(sql, verbose=True)
    assert df["FCTY_CODE"][0] == "JSFC"
