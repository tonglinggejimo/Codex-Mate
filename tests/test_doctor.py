from pathlib import Path

from codex_mate import doctor


def test_doctor_collects_windows_direct_launcher_status(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    monkeypatch.setattr(doctor.runtime, "is_frozen", lambda: False)
    monkeypatch.setattr(doctor.watcher, "watcher_disabled_flag", lambda: tmp_path / "watcher.disabled")
    monkeypatch.setattr(doctor.watcher, "watcher_lock_path", lambda debug_port: tmp_path / f"watcher-{debug_port}.lock")
    monkeypatch.setattr(doctor.app_paths, "codex_app_dir_cache_path", lambda: tmp_path / "codex_app_dir.txt")
    monkeypatch.setattr(doctor.app_paths, "resolve_codex_app_dir", lambda: Path("C:/Codex/app"))
    monkeypatch.setattr(doctor, "port_listening", lambda port: port == 57321)
    (tmp_path / "watcher.disabled").touch()
    (tmp_path / "codex_app_dir.txt").write_text("C:/Codex/app", encoding="utf-8")

    payload = doctor.collect_status()

    assert payload["platform"] == "win32"
    assert payload["watcher"]["enabled"] is False
    assert payload["watcher"]["lock_exists"] is False
    assert payload["ports"]["helper_57321"] is True
    assert payload["ports"]["cdp_9229"] is False
    assert payload["codex_app"]["cache_exists"] is True
    assert payload["codex_app"]["resolved_dir"] == "C:/Codex/app"
