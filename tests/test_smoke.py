import pytest

from portable_handoff import __version__
from portable_handoff.cli import main


def test_package_version_and_help(capsys):
    assert __version__ == "0.1.0"
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "portable-handoff" in capsys.readouterr().out
