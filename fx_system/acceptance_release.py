"""Local Release API substitute for offline acceptance only."""
import json
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit

from .acceptance_target import enabled
from .backtest_release_store import REPOSITORY, TAG, LIMIT, digest


class AcceptanceRelease:
    def __init__(self, root):
        if not enabled():
            raise ValueError("offline Release adapter requires acceptance mode")
        directory = root / ".private-acceptance"
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("offline acceptance directory required")
        path = directory / "release.sqlite"
        if path.is_symlink():
            raise ValueError("offline Release database cannot be a symlink")
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS release (id INTEGER PRIMARY KEY, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assets (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                              name TEXT UNIQUE NOT NULL, payload BLOB NOT NULL,
                                              size INTEGER NOT NULL, checksum TEXT NOT NULL);
        """)
        self.calls, self.remaining = 0, 5000

    def reserve(self, count):
        if self.calls + count > 64:
            raise ValueError("offline Release request budget exhausted")

    def request(self, method, path, *, body=None, raw=None, binary=False, missing=False):
        self.reserve(1)
        self.calls += 1
        self.remaining -= 1
        route = urlsplit(path)
        parameters = parse_qs(route.query)
        if method == "GET" and path == "":
            return {"full_name": REPOSITORY, "private": True}
        if path == "/releases/tags/" + TAG and method == "GET":
            row = self.db.execute("SELECT document FROM release WHERE id=1").fetchone()
            return json.loads(row[0]) if row else None
        if method == "POST" and path == "/releases" and body.get("tag_name") == TAG:
            document = {**body, "id": 1}
            with self.db:
                self.db.execute("INSERT INTO release VALUES(1,?)", (json.dumps(document),))
            return document
        if route.path == "/releases/1/assets":
            if method == "GET":
                offset = (int(parameters["page"][0]) - 1) * 100
                return [self.asset(*item) for item in self.db.execute(
                    "SELECT id,name,size,checksum FROM assets ORDER BY id LIMIT 100 OFFSET ?", (offset,))]
            if method == "UPLOAD" and isinstance(raw, bytes) and len(raw) <= LIMIT:
                name, = parameters["name"]
                checksum = digest(raw)
                with self.db:
                    item = self.db.execute("INSERT INTO assets(name,payload,size,checksum) VALUES(?,?,?,?)",
                                           (name, raw, len(raw), checksum))
                return self.asset(item.lastrowid, name, len(raw), checksum)
        if path == "/releases/1" and method in ("GET", "PATCH"):
            document = json.loads(self.db.execute("SELECT document FROM release WHERE id=1").fetchone()[0])
            if method == "PATCH":
                document.update(body)
                with self.db:
                    self.db.execute("UPDATE release SET document=? WHERE id=1", (json.dumps(document),))
            return document
        if re.fullmatch(r"/releases/assets/[0-9]+", path):
            number = int(path.rsplit("/", 1)[1])
            if method == "GET" and binary:
                return self.db.execute("SELECT payload FROM assets WHERE id=?", (number,)).fetchone()[0]
            if method == "DELETE":
                with self.db:
                    self.db.execute("DELETE FROM assets WHERE id=?", (number,))
                return None
        raise ValueError("unsupported offline Release operation")

    @staticmethod
    def asset(number, name, size, checksum):
        return {"id": number, "name": name, "state": "uploaded",
                "size": size, "digest": "sha256:" + checksum}
