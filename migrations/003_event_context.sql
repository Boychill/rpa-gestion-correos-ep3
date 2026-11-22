CREATE TABLE IF NOT EXISTS event_context(
 event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
 dataset TEXT, job_id TEXT, role TEXT, http_status INTEGER,
 wait_ms REAL NOT NULL DEFAULT 0, recovery TEXT NOT NULL DEFAULT 'NONE'
);
INSERT OR IGNORE INTO schema_version(version) VALUES(3);
