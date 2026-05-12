import sqlite3
from pathlib import Path

from codex_mate.file_tree import ProjectFileTreeService


def create_threads_db(path: Path, cwds: list[tuple[str, int]]) -> None:
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                cwd TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        for index, (cwd, updated_at) in enumerate(cwds):
            db.execute(
                "INSERT INTO threads (id, cwd, updated_at, archived) VALUES (?, ?, ?, 0)",
                (f"t{index}", cwd, updated_at),
            )


def root_id_for(payload: dict[str, object], path: Path) -> str:
    resolved = str(path.resolve())
    for root in payload["roots"]:
        if root["path"] == resolved:
            return root["id"]
    raise AssertionError(f"root not found for {resolved}")


def test_file_tree_roots_read_existing_thread_cwds_in_recent_order(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    missing = tmp_path / "missing"
    first.mkdir()
    second.mkdir()
    db_path = tmp_path / "state_5.sqlite"
    create_threads_db(
        db_path,
        [
            (str(first), 100),
            (str(missing), 300),
            ("", 400),
            (str(second), 200),
            (str(first), 500),
        ],
    )

    payload = ProjectFileTreeService(db_path).roots()

    assert payload["status"] == "ok"
    assert [root["path"] for root in payload["roots"]] == [str(first.resolve()), str(second.resolve())]
    assert payload["roots"][0]["name"] == "first"


def test_file_tree_lists_directories_first_ignores_large_dirs_and_limits_results(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / ".git").mkdir()
    (project / "README.md").write_text("readme", encoding="utf-8")
    for index in range(3):
        (project / f"file-{index}.txt").write_text(str(index), encoding="utf-8")
    db_path = tmp_path / "state_5.sqlite"
    create_threads_db(db_path, [(str(project), 100)])
    service = ProjectFileTreeService(db_path, max_entries=3)
    roots = service.roots()

    payload = service.list_dir(root_id_for(roots, project), "")

    assert payload["status"] == "ok"
    assert payload["truncated"] is True
    assert [item["name"] for item in payload["items"]] == ["src", "file-0.txt", "file-1.txt"]
    assert ".git" not in [item["name"] for item in payload["items"]]
    assert payload["items"][0]["type"] == "directory"


def test_file_tree_rejects_unknown_root_and_paths_outside_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    db_path = tmp_path / "state_5.sqlite"
    create_threads_db(db_path, [(str(project), 100)])
    service = ProjectFileTreeService(db_path)
    roots = service.roots()
    root_id = root_id_for(roots, project)

    unknown = service.list_dir("missing-root", "")
    escaped = service.read_file(root_id, "../outside.txt")

    assert unknown["status"] == "failed"
    assert "Unknown project root" in unknown["message"]
    assert escaped["status"] == "failed"
    assert "outside project root" in escaped["message"]


def test_file_tree_rejects_symlink_that_resolves_outside_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (project / "linked").symlink_to(outside, target_is_directory=True)
    db_path = tmp_path / "state_5.sqlite"
    create_threads_db(db_path, [(str(project), 100)])
    service = ProjectFileTreeService(db_path)
    roots = service.roots()

    payload = service.list_dir(root_id_for(roots, project), "linked")

    assert payload["status"] == "failed"
    assert "outside project root" in payload["message"]


def test_file_tree_reads_text_and_rejects_binary_or_too_large_files(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "note.txt").write_text("hello\n", encoding="utf-8")
    (project / "image.bin").write_bytes(b"\x00\x01\x02")
    (project / "large.txt").write_text("abcdef", encoding="utf-8")
    db_path = tmp_path / "state_5.sqlite"
    create_threads_db(db_path, [(str(project), 100)])
    service = ProjectFileTreeService(db_path, max_preview_bytes=5)
    roots = service.roots()
    root_id = root_id_for(roots, project)

    text = ProjectFileTreeService(db_path).read_file(root_id, "note.txt")
    binary = service.read_file(root_id, "image.bin")
    large = service.read_file(root_id, "large.txt")

    assert text["status"] == "ok"
    assert text["content"] == "hello\n"
    assert text["path"] == "note.txt"
    assert binary["status"] == "binary"
    assert large["status"] == "too_large"
