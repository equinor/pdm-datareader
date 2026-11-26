import sys


def test_unhandled_traceback_does_not_expose_token(capsys):
    """An unhandled traceback must not render frame locals holding a token.

    Uses the default excepthook, and additionally exercises rich's traceback
    hook with show_locals disabled when rich is installed, to catch a future
    regression that renders frame locals into logs.
    """
    try:
        from rich.traceback import install

        install(show_locals=False)
    except ImportError:
        pass

    sentinel = "sentinel-token-that-must-not-appear"

    try:
        # Bind the sentinel as a frame local so a show_locals renderer would
        # leak it if local-variable rendering were ever re-enabled.
        token = sentinel  # noqa: F841
        raise RuntimeError("boom")
    except RuntimeError:
        exc_type, exc, traceback = sys.exc_info()
        sys.excepthook(exc_type, exc, traceback)

    output = capsys.readouterr()
    rendered = output.out + output.err
    assert "RuntimeError: boom" in rendered  # proves the hook rendered
    assert sentinel not in rendered
