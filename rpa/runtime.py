"""Entrada: perfil y operaciones. Salida: bloqueo, presupuesto y auditoría sanitizada."""
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
import logging
import json
import os
import socket
import time

from rpa.store import utcnow


class RPAError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class Budget:
    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds

    def remaining(self):
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise RPAError("BUDGET_EXHAUSTED")
        return value

    def sleep(self, seconds):
        if seconds >= self.remaining():
            raise RPAError("RETRY_EXCEEDS_BUDGET")
        time.sleep(seconds)


@contextmanager
def profile_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    file = path.open("a+b")
    if file.tell() == 0:
        file.write(b"0")
        file.flush()
    file.seek(0)
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise RPAError("PROFILE_BUSY") from exc
        yield
    finally:
        if locked:
            file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_UN)
        file.close()


class Audit:
    def __init__(self, store, execution_id, directory):
        self.store, self.execution_id = store, execution_id
        directory.mkdir(parents=True, exist_ok=True)
        self.logger = logging.Logger(execution_id, level=logging.DEBUG)
        for level in (logging.DEBUG, logging.INFO, logging.ERROR):
            name = logging.getLevelName(level)
            handler = RotatingFileHandler(directory / f"{execution_id}.{name}.log", maxBytes=1_000_000,
                                          backupCount=3, encoding="utf-8")
            handler.addFilter(lambda record, target=level: record.levelno == target)
            self.logger.addHandler(handler)

    def event(self, step, start, elapsed, attempt=1, result="OK", code="OK", context=None):
        level = "INFO" if result == "OK" else "ERROR"
        finished = utcnow()
        # Nunca incluir str(exception), URLs, asuntos, remitentes ni respuestas OAuth.
        inserted = self.store.execute("INSERT INTO events VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?)",
                           (self.execution_id, step, socket.gethostname(), start, finished, elapsed,
                            attempt, level, result, code, code))
        context = context or {}
        self.store.execute('INSERT INTO event_context VALUES(?,?,?,?,?,?,?)',
            (inserted.lastrowid, context.get('dataset'), context.get('job_id'), context.get('role'),
             context.get('http_status'), context.get('wait_ms', 0), context.get('recovery', 'NONE')))
        self.logger.log(logging.INFO if result == "OK" else logging.ERROR, "%s", json.dumps({
            "execution_id": self.execution_id, "step_id": step, "started": start, "finished": finished,
            "duration_ms": round(elapsed, 3), "attempt": attempt, "retries": max(0, attempt-1),
            "level": level, "status": result, "code": code, **context}, ensure_ascii=False))

    @contextmanager
    def step(self, name, attempt=1, context=None):
        start, timer = utcnow(), time.monotonic()
        try:
            yield
        except Exception as exc:
            self.event(name, start, (time.monotonic()-timer)*1000, attempt, "FAILED",
                       exc.code if isinstance(exc, RPAError) else type(exc).__name__, context=context)
            raise
        else:
            self.event(name, start, (time.monotonic()-timer)*1000, attempt, context=context)

    def close(self):
        for handler in self.logger.handlers:
            handler.close()
