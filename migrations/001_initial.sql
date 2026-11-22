CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES (1);
CREATE TABLE IF NOT EXISTS executions(
 id TEXT PRIMARY KEY, profile TEXT NOT NULL, signature TEXT NOT NULL, started TEXT NOT NULL,
 finished TEXT, status TEXT NOT NULL, source TEXT NOT NULL, metrics TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS execution_status ON executions(profile,status);
CREATE TABLE IF NOT EXISTS messages(
 mailbox TEXT NOT NULL, id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
 received TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
 category TEXT, rule TEXT, rules_version TEXT, PRIMARY KEY(mailbox,id));
CREATE INDEX IF NOT EXISTS message_status ON messages(state,received);
CREATE TABLE IF NOT EXISTS run_messages(
 execution_id TEXT NOT NULL REFERENCES executions(id), mailbox TEXT NOT NULL, message_id TEXT NOT NULL,
 snapshot TEXT NOT NULL, PRIMARY KEY(execution_id,mailbox,message_id));
CREATE TABLE IF NOT EXISTS checkpoints(scope TEXT PRIMARY KEY, cursor TEXT, phase TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS operations(
 execution_id TEXT NOT NULL REFERENCES executions(id), op TEXT NOT NULL, attempts INTEGER NOT NULL,
 PRIMARY KEY(execution_id,op));
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES executions(id), step_id TEXT NOT NULL,
 host TEXT NOT NULL, started TEXT NOT NULL, finished TEXT NOT NULL, duration_ms REAL NOT NULL,
 attempt INTEGER NOT NULL, level TEXT NOT NULL, result TEXT NOT NULL, code TEXT NOT NULL, message TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_filters ON events(execution_id,started,level,step_id);
CREATE INDEX IF NOT EXISTS event_level_date ON events(level,started);
CREATE TABLE IF NOT EXISTS sends(
 execution_id TEXT PRIMARY KEY REFERENCES executions(id), state TEXT NOT NULL,
 sha256 TEXT NOT NULL, size INTEGER NOT NULL, prepared TEXT NOT NULL, updated TEXT NOT NULL,
 adapter TEXT NOT NULL, reconciliation TEXT);
CREATE TABLE IF NOT EXISTS cleanups(
 id TEXT PRIMARY KEY, created TEXT NOT NULL, state TEXT NOT NULL, manifest TEXT NOT NULL,
 archive_hash TEXT NOT NULL, result TEXT);
