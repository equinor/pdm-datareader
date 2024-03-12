import shutil
import pathlib

from pdm_tools import tools

sql = "SELECT [FCTY_CODE] FROM [PDMVW].[FACILITY_MASTER] WHERE STID_CODE = 'JSV'"


def test_normal():
    df = tools.query(sql)
    assert df["FCTY_CODE"][0] == "JSFC"


def test_handle_invalid_tokens():
    prepare_test("token_cache_invalid_user.bin")
    df = tools.query(sql, verbose=True)
    assert df["FCTY_CODE"][0] == "JSFC"

    prepare_test("token_cache_actually.txt")
    df = tools.query(sql, verbose=True)
    assert df["FCTY_CODE"][0] == "JSFC"

    prepare_test("token_cache_invalid_filetype.bmp")
    df = tools.query(sql, verbose=True)
    assert df["FCTY_CODE"][0] == "JSFC"


def prepare_test(filename: str):
    dest = replace_file(filename)
    tools.set_token_location(dest)


def replace_file(filename: str) -> str:
    dir_path = pathlib.Path(__file__).parent
    dest = dir_path.joinpath("tmp", "token_cache_invalid.bin")
    source = dir_path.joinpath(filename)
    dest.unlink(missing_ok=True)

    if not dest.parent.is_dir():
        dest.parent.mkdir()
    shutil.copyfile(src=source, dst=dest)

    return dest
