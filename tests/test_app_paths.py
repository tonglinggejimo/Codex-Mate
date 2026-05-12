from pathlib import Path

from codex_mate import app_paths
from codex_mate.app_paths import find_latest_codex_app_dir, find_macos_codex_app, resolve_codex_app_dir, user_data_candidates


def test_find_latest_codex_app_dir_uses_highest_version(tmp_path):
    older = tmp_path / "OpenAI.Codex_1.2.3.0_x64__abc" / "app"
    newer = tmp_path / "OpenAI.Codex_26.429.8261.0_x64__abc" / "app"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)

    assert find_latest_codex_app_dir(tmp_path) == newer


def test_find_latest_codex_app_dir_uses_valid_windows_cache_before_powershell(monkeypatch, tmp_path):
    cached = tmp_path / "OpenAI.Codex_26.506.1.0_x64__abc" / "app"
    cached.mkdir(parents=True)
    (cached / "Codex.exe").write_text("", encoding="utf-8")
    cache_file = tmp_path / ".codex-mate" / "codex_app_dir.txt"
    cache_file.parent.mkdir()
    cache_file.write_text(str(cached), encoding="utf-8")
    monkeypatch.setattr(app_paths, "codex_app_dir_cache_path", lambda: cache_file)
    monkeypatch.setattr(app_paths.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("PowerShell should not run")))

    assert find_latest_codex_app_dir() == cached


def test_find_latest_codex_app_dir_writes_windows_cache_after_powershell(monkeypatch, tmp_path):
    discovered_root = tmp_path / "OpenAI.Codex_26.506.2.0_x64__abc"
    discovered = discovered_root / "app"
    discovered.mkdir(parents=True)
    (discovered / "Codex.exe").write_text("", encoding="utf-8")
    cache_file = tmp_path / ".codex-mate" / "codex_app_dir.txt"
    monkeypatch.setattr(app_paths, "codex_app_dir_cache_path", lambda: cache_file)

    class Result:
        returncode = 0
        stdout = str(discovered_root)

    calls = []
    monkeypatch.setattr(app_paths.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)) or Result())

    assert find_latest_codex_app_dir() == discovered
    assert cache_file.read_text(encoding="utf-8") == str(discovered)
    assert calls[0][1]["creationflags"] == getattr(app_paths.subprocess, "CREATE_NO_WINDOW", 0)


def test_user_data_candidates_include_local_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))

    candidates = user_data_candidates()

    assert Path(tmp_path / "Local" / "OpenAI" / "Codex") in candidates


def test_find_macos_codex_app_prefers_applications(tmp_path):
    system_app = tmp_path / "Applications" / "Codex.app"
    user_app = tmp_path / "Users" / "me" / "Applications" / "Codex.app"
    system_app.mkdir(parents=True)
    user_app.mkdir(parents=True)

    result = find_macos_codex_app([system_app, user_app])

    assert result == system_app


def test_find_macos_codex_app_detects_openai_codex_bundle(tmp_path):
    openai_app = tmp_path / "Applications" / "OpenAI Codex.app"
    openai_app.mkdir(parents=True)

    result = find_macos_codex_app([tmp_path / "Applications"])

    assert result == openai_app


def test_find_macos_codex_app_returns_none_when_missing(tmp_path):
    result = find_macos_codex_app([tmp_path / "Applications" / "Codex.app"])

    assert result is None


def test_resolve_codex_app_dir_uses_macos_discovery_on_darwin(monkeypatch, tmp_path):
    mac_app = tmp_path / "Applications" / "OpenAI Codex.app"
    mac_app.mkdir(parents=True)
    monkeypatch.setattr("codex_mate.app_paths.sys.platform", "darwin")
    monkeypatch.setattr("codex_mate.app_paths.find_macos_codex_app", lambda: mac_app)
    monkeypatch.setattr("codex_mate.app_paths.find_latest_codex_app_dir", lambda: None)

    assert resolve_codex_app_dir() == mac_app
