import pytest
import solaar


@pytest.fixture
def rule_dirs(tmp_path, monkeypatch):
    dirs = [tmp_path / "etc", tmp_path / "usr"]
    for directory in dirs:
        directory.mkdir()
    monkeypatch.setattr(solaar, "_UDEV_RULE_DIRS", tuple(str(d) for d in dirs))
    return dirs


def test_udev_rule_missing(rule_dirs):
    assert solaar.udev_rule_installed() is False


@pytest.mark.parametrize("index", [0, 1])
def test_udev_rule_found_in_any_directory(rule_dirs, index):
    (rule_dirs[index] / solaar.UDEV_RULE).write_text("# rule\n")

    assert solaar.udev_rule_installed() is True


def test_rule_files_ship_with_the_source():
    from pathlib import Path

    rules = Path(__file__).resolve().parents[2] / "rules.d"
    hidraw = (rules / solaar.UDEV_RULE).read_text()
    uinput = (rules / "42-plasmaar-uinput.rules").read_text()

    assert 'TAG+="uaccess"' in hidraw and 'KERNELS == "0005:046D:*"' in hidraw
    assert "uinput" not in hidraw.split("#")[-1]  # input injection is opt-in, in its own file
    assert 'KERNEL=="uinput"' in uinput
