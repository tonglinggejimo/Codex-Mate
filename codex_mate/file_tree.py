from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_IGNORED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
}


@dataclass(frozen=True)
class FileTreeRoot:
    id: str
    name: str
    path: Path
    updated_at: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "path": str(self.path),
            "updated_at": self.updated_at,
        }


class ProjectFileTreeService:
    def __init__(
        self,
        db_path: Path | None,
        *,
        max_entries: int = 500,
        max_preview_bytes: int = 256 * 1024,
        ignored_names: set[str] | None = None,
    ):
        self.db_path = db_path
        self.max_entries = max_entries
        self.max_preview_bytes = max_preview_bytes
        self.ignored_names = ignored_names or DEFAULT_IGNORED_NAMES

    def roots(self) -> dict[str, object]:
        return {"status": "ok", "roots": [root.to_dict() for root in self._roots()]}

    def list_dir(self, root_id: str, path: str = "") -> dict[str, object]:
        root = self._root_by_id(root_id)
        if root is None:
            return self._failed("Unknown project root")
        directory, error = self._safe_path(root.path, path)
        if error:
            return self._failed(error)
        if not directory.is_dir():
            return self._failed("Path is not a directory")

        items: list[dict[str, object]] = []
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            return self._failed(str(exc))

        for child in children:
            if child.name in self.ignored_names:
                continue
            try:
                resolved = child.resolve()
            except OSError:
                continue
            if not self._is_inside(root.path, resolved):
                continue
            if child.is_dir():
                item_type = "directory"
                size = None
            elif child.is_file():
                item_type = "file"
                try:
                    size = child.stat().st_size
                except OSError:
                    size = None
            else:
                continue
            items.append(
                {
                    "name": child.name,
                    "path": self._relative_posix(root.path, resolved),
                    "type": item_type,
                    "size": size,
                }
            )

        items.sort(key=lambda item: (0 if item["type"] == "directory" else 1, str(item["name"]).lower()))
        truncated = len(items) > self.max_entries
        return {
            "status": "ok",
            "root_id": root.id,
            "path": self._relative_posix(root.path, directory),
            "items": items[: self.max_entries],
            "truncated": truncated,
        }

    def read_file(self, root_id: str, path: str) -> dict[str, object]:
        root = self._root_by_id(root_id)
        if root is None:
            return self._failed("Unknown project root")
        file_path, error = self._safe_path(root.path, path)
        if error:
            return self._failed(error)
        if not file_path.is_file():
            return self._failed("Path is not a file")

        try:
            size = file_path.stat().st_size
        except OSError as exc:
            return self._failed(str(exc))
        if size > self.max_preview_bytes:
            return {
                "status": "too_large",
                "message": f"文件超过 {self.max_preview_bytes} 字节，未预览。",
                "path": self._relative_posix(root.path, file_path),
                "size": size,
                "max_bytes": self.max_preview_bytes,
            }

        try:
            raw = file_path.read_bytes()
        except OSError as exc:
            return self._failed(str(exc))
        if b"\x00" in raw:
            return {
                "status": "binary",
                "message": "二进制文件不支持预览。",
                "path": self._relative_posix(root.path, file_path),
                "size": size,
            }
        try:
            content = raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            return {
                "status": "binary",
                "message": "文件不是 UTF-8 文本，未预览。",
                "path": self._relative_posix(root.path, file_path),
                "size": size,
            }
        return {
            "status": "ok",
            "path": self._relative_posix(root.path, file_path),
            "name": file_path.name,
            "content": content,
            "encoding": encoding,
            "size": size,
        }

    def _roots(self) -> list[FileTreeRoot]:
        if self.db_path is None or not self.db_path.exists():
            return []
        try:
            with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=10) as db:
                db.row_factory = sqlite3.Row
                if not self._table_exists(db, "threads"):
                    return []
                columns = self._table_columns(db, "threads")
                if "cwd" not in columns:
                    return []
                selected = ["cwd"]
                if "updated_at" in columns:
                    selected.append("updated_at")
                if "archived" in columns:
                    selected.append("archived")
                rows = db.execute(f"SELECT {', '.join(selected)} FROM threads").fetchall()
        except sqlite3.Error:
            return []

        latest_by_path: dict[Path, int] = {}
        for row in rows:
            if "archived" in row.keys() and int(row["archived"] or 0) != 0:
                continue
            cwd = str(row["cwd"] or "").strip()
            if not cwd:
                continue
            try:
                path = Path(cwd).expanduser().resolve()
            except OSError:
                continue
            if not path.is_dir():
                continue
            updated_at = int(row["updated_at"] or 0) if "updated_at" in row.keys() else 0
            latest_by_path[path] = max(updated_at, latest_by_path.get(path, 0))

        roots = [
            FileTreeRoot(id=self._root_id(path), name=path.name or str(path), path=path, updated_at=updated_at)
            for path, updated_at in latest_by_path.items()
        ]
        roots.sort(key=lambda root: (-root.updated_at, str(root.path).lower()))
        return roots

    def _root_by_id(self, root_id: str) -> FileTreeRoot | None:
        return next((root for root in self._roots() if root.id == root_id), None)

    def _safe_path(self, root: Path, path: str) -> tuple[Path, str | None]:
        try:
            candidate = (root / path).resolve()
        except OSError as exc:
            return root, str(exc)
        if not self._is_inside(root, candidate):
            return candidate, "Path is outside project root"
        return candidate, None

    @staticmethod
    def _table_exists(db: sqlite3.Connection, table: str) -> bool:
        return db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None

    @staticmethod
    def _table_columns(db: sqlite3.Connection, table: str) -> set[str]:
        return {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def _root_id(path: Path) -> str:
        return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _is_inside(root: Path, path: Path) -> bool:
        return path == root or root in path.parents

    @staticmethod
    def _relative_posix(root: Path, path: Path) -> str:
        try:
            relative = path.relative_to(root)
        except ValueError:
            return ""
        return "" if str(relative) == "." else relative.as_posix()

    @staticmethod
    def _failed(message: str) -> dict[str, object]:
        return {"status": "failed", "message": message}
