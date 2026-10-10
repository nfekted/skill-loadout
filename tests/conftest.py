import pytest


@pytest.fixture(autouse=True)
def loadout_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("LOADOUT_HOME", str(home))
    return home
