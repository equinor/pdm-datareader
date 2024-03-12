import os
import shutil

from pdm_tools import tools
from msal_bearer.BearerAuth import set_token_location


def replace_file(filename: str) -> str:
    dir_path = os.path.dirname(os.path.realpath(__file__))
    dest = os.path.join(dir_path, "tmp", "token_cache_invalid.bin")
    source = os.path.join(dir_path, filename)

    try:
        os.remove(dest)
    except OSError:
        pass
    if not os.path.isdir(os.path.join(dir_path, "tmp")):
        os.mkdir(os.path.join(dir_path, "tmp"))
    shutil.copyfile(src=source, dst=dest)

    return dest

sql = "SELECT [FCTY_CODE] FROM [PDMVW].[FACILITY_MASTER] WHERE STID_CODE = 'JSV'"

def test_normal():
    df = tools.query(sql)
    assert df["FCTY_CODE"][0] == "JSFC"


def test_handle_invalid_tokens():
    set_token_location(replace_file("token_cache_invalid_user.bin"))
    df = tools.query(sql, verbose=True)
    assert df["FCTY_CODE"][0] == "JSFC"

    set_token_location(replace_file("token_cache_actually.txt"))
    df = tools.query(sql, verbose=True)
    assert df["FCTY_CODE"][0] == "JSFC"

    set_token_location(replace_file("token_cache_invalid_filetype.bmp"))
    df = tools.query(sql, verbose=True)
    assert df["FCTY_CODE"][0] == "JSFC"
