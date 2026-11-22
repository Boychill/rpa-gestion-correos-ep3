"""Entrada: páginas/cambios. Salida: estado durable. Errores: sqlite3/ValueError.
La página aceptada y su cursor se confirman en una sola transacción.
"""
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import hashlib
import json
import sqlite3


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Store(AbstractContextManager):
    def __init__(self, path, root):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript((root / "migrations/001_initial.sql").read_text(encoding="utf-8"))
        if not self.row("SELECT version FROM schema_version WHERE version=2"):
            self.db.executescript((root / "migrations/002_cloud_logs.sql").read_text(encoding="utf-8"))
        if not self.row("SELECT version FROM schema_version WHERE version=3"):
            self.db.executescript((root / "migrations/003_event_context.sql").read_text(encoding="utf-8"))

    def __exit__(self, *args):
        self.db.close()

    def row(self, sql, args=()):
        return self.db.execute(sql, args).fetchone()

    def rows(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def execute(self, sql, args=()):
        with self.db:
            return self.db.execute(sql, args)

    def ingest(self, execution_id, mailbox, scope, messages, cursor, phase, before_commit=None):
        counts = {"new": 0, "updated": 0, "duplicates": 0, "removed": 0}
        with self.db:
            for msg in messages:
                mid = msg["id"]
                old = self.row("SELECT * FROM messages WHERE mailbox=? AND id=?", (mailbox, mid))
                if msg.get("removed"):
                    self.db.execute("UPDATE messages SET state='REMOVED' WHERE mailbox=? AND id=?", (mailbox, mid))
                    self.db.execute("DELETE FROM run_messages WHERE execution_id=? AND mailbox=? AND message_id=?",
                                    (execution_id, mailbox, mid))
                    counts["removed"] += 1
                    continue
                payload = encode(msg)
                fingerprint = hashlib.sha256(payload.encode()).hexdigest()
                if old and old["fingerprint"] == fingerprint and old["state"] != "REMOVED":
                    counts["duplicates"] += 1
                    continue
                counts["updated" if old else "new"] += 1
                self.db.execute("""INSERT INTO messages(mailbox,id,fingerprint,payload,received)
                    VALUES(?,?,?,?,?) ON CONFLICT(mailbox,id) DO UPDATE SET fingerprint=excluded.fingerprint,
                    payload=excluded.payload,received=excluded.received,state='PENDING',attempts=0,
                    category=NULL,rule=NULL,rules_version=NULL""", (mailbox, mid, fingerprint, payload, msg["received"]))
                self.db.execute("INSERT OR REPLACE INTO run_messages VALUES(?,?,?,?)",
                                (execution_id, mailbox, mid, payload))
            self.db.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)", (scope, cursor, phase))
            if before_commit:
                before_commit()
        return counts

    def classify_batch(self, execution_id, classifier, limit, max_attempts):
        rows = self.rows("""SELECT m.* FROM messages m JOIN run_messages r
            ON m.mailbox=r.mailbox AND m.id=r.message_id WHERE r.execution_id=?
            AND m.state='PENDING' AND m.attempts<? LIMIT ?""", (execution_id, max_attempts, limit))
        with self.db:
            for row in rows:
                msg = json.loads(row["payload"])
                try:
                    category, rule, version = classifier.classify(msg["subject"])
                    self.db.execute("""UPDATE messages SET state='CLASSIFIED',attempts=attempts+1,
                        category=?,rule=?,rules_version=? WHERE mailbox=? AND id=?""",
                        (category, rule, version, row["mailbox"], row["id"]))
                    msg.update(category=category, rule=rule, rules_version=version)
                    self.db.execute("UPDATE run_messages SET snapshot=? WHERE execution_id=? AND mailbox=? AND message_id=?",
                                    (encode(msg), execution_id, row["mailbox"], row["id"]))
                except (ValueError, TypeError):
                    self.db.execute("""UPDATE messages SET attempts=attempts+1,
                        state=CASE WHEN attempts+1>=? THEN 'REVIEW' ELSE 'PENDING' END WHERE mailbox=? AND id=?""",
                        (max_attempts, row["mailbox"], row["id"]))
        return len(rows)

    def items(self, execution_id):
        return [json.loads(r[0]) for r in self.rows(
            "SELECT snapshot FROM run_messages WHERE execution_id=? ORDER BY message_id", (execution_id,))]
