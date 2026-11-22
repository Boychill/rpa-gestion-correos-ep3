BEGIN;
CREATE TABLE IF NOT EXISTS log_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS log_outbox(
 id TEXT PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES executions(id), payload TEXT NOT NULL,
 digest TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('PENDING','IN_FLIGHT','SYNCED','REVIEW','BLOCKED')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0), next_attempt TEXT NOT NULL,
 code TEXT NOT NULL DEFAULT 'OK', updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS log_outbox_due ON log_outbox(state,next_attempt,attempts);
CREATE TABLE IF NOT EXISTS log_files(
 name TEXT PRIMARY KEY, execution_id TEXT REFERENCES executions(id), created TEXT NOT NULL,
 expires TEXT NOT NULL, sha256 TEXT NOT NULL, source TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'ACTIVE');
INSERT OR IGNORE INTO schema_version VALUES (2);
COMMIT;
