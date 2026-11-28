"""Isolated partition publisher. SQLite owns the atomic generation pointer."""
import json
import lzma
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import contextmanager

from .events import MAX_RAW, canonical, sha
from .partition_budget import OBJECT_RESERVE, PARTITION_LIMIT, PLAN_NEXT_PARTITION


class PartitionStore:
    def __init__(self, root, *, prepare=PLAN_NEXT_PARTITION, limit=PARTITION_LIMIT):
        if not OBJECT_RESERVE < prepare < limit <= PARTITION_LIMIT:
            raise ValueError("invalid partition budget")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.prepare, self.limit = prepare, limit
        self.db = sqlite3.connect(self.root / "index.sqlite")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS partitions(id INTEGER PRIMARY KEY, used INTEGER NOT NULL);
            INSERT OR IGNORE INTO partitions VALUES(0, 0);
            CREATE TABLE IF NOT EXISTS objects(key TEXT PRIMARY KEY, partition INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS generations(id INTEGER PRIMARY KEY, root TEXT NOT NULL);
        """)

    @contextmanager
    def publish(self, expected):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            head = self.db.execute("SELECT max(id) FROM generations").fetchone()[0]
            if head != expected:
                raise ValueError("stale generation")
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def advance(self, generation, root):
        if not self.db.in_transaction:
            raise ValueError("publish transaction required")
        self.get(root)
        self.db.execute("INSERT INTO generations VALUES(?, ?)", (generation, root))

    def roots(self):
        return self.db.execute("SELECT id,root FROM generations ORDER BY id DESC LIMIT 3").fetchall()

    def put(self, value):
        if not self.db.in_transaction:
            raise ValueError("publish transaction required")
        raw = canonical(value)
        if len(raw) > MAX_RAW:
            raise ValueError("raw object exceeds limit")
        key = sha(raw)
        if self.db.execute("SELECT 1 FROM objects WHERE key=?", (key,)).fetchone():
            self.get(key)
            return key
        compressed = lzma.compress(raw, preset=1)
        cost = len(compressed) + OBJECT_RESERVE
        if len(compressed) > MAX_RAW or cost > self.limit:
            raise ValueError("object cannot fit in a partition")
        partition, used = self.db.execute(
            "SELECT id,used FROM partitions WHERE used>0 OR id=0 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if used + cost > self.limit:
            partition += 1
            used = 0
        directory = self.root / str(partition)
        directory.mkdir(exist_ok=True)
        path = directory / key
        with tempfile.NamedTemporaryFile(dir=directory) as pending:
            pending.write(compressed)
            pending.flush()
            os.fsync(pending.fileno())
            try:
                os.link(pending.name, path)
            except FileExistsError:
                if self.read(path, key) != value:
                    raise ValueError("unpublished object corrupt")
        self.db.execute("INSERT OR IGNORE INTO partitions VALUES(?, 0)", (partition,))
        self.db.execute("UPDATE partitions SET used=? WHERE id=?", (used + cost, partition))
        if used + cost >= self.prepare:
            (self.root / str(partition + 1)).mkdir(exist_ok=True)
            self.db.execute("INSERT OR IGNORE INTO partitions VALUES(?, 0)", (partition + 1,))
        self.db.execute("INSERT INTO objects VALUES(?, ?)", (key, partition))
        return key

    def get(self, key):
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("invalid object key")
        found = self.db.execute("SELECT partition FROM objects WHERE key=?", (key,)).fetchone()
        if found is None:
            raise ValueError("missing object")
        return self.read(self.root / str(found[0]) / key, key)

    @staticmethod
    def read(path, key):
        with path.open("rb") as source:
            payload = source.read(MAX_RAW + 1)
        if len(payload) > MAX_RAW:
            raise ValueError("compressed object exceeds limit")
        try:
            decoder = lzma.LZMADecompressor(memlimit=32 * 1024 * 1024)
            raw = decoder.decompress(payload, max_length=MAX_RAW + 1)
        except lzma.LZMAError as error:
            raise ValueError("invalid compressed object") from error
        if len(raw) > MAX_RAW or not decoder.eof or decoder.unused_data or sha(raw) != key:
            raise ValueError("invalid object digest or size")
        return json.loads(raw)
