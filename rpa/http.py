"""GET idempotente con intentos persistentes. POST de envío no utiliza este retry."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import httpx
import time
import random
from urllib.parse import urlparse

from rpa.runtime import RPAError


def retry_delay(value, attempt):
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                return max(0.0, (parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError):
                pass
    return min(2 ** (attempt-1) + random.uniform(0, .25), 30)


class ReaderHTTP:
    def __init__(self, client, settings, store, execution_id, audit, budget):
        self.client, self.settings, self.store = client, settings, store
        self.execution_id, self.audit, self.budget = execution_id, audit, budget
        self.queries = self.retries = 0

    def get(self, url, headers=None):
        batch_deadline = time.monotonic() + self.settings.batch_seconds
        key = hashlib.sha256(url.encode()).hexdigest()
        row = self.store.row("SELECT attempts FROM operations WHERE execution_id=? AND op=?", (self.execution_id, key))
        used = row[0] if row else 0
        for attempt in range(used+1, self.settings.max_attempts+1):
            batch_remaining = batch_deadline - time.monotonic()
            if batch_remaining <= 0:
                raise RPAError("BATCH_BUDGET_EXHAUSTED")
            timeout = min(self.settings.http_timeout, self.budget.remaining(), batch_remaining)
            self.store.execute("INSERT OR REPLACE INTO operations VALUES(?,?,?)", (self.execution_id, key, attempt))
            self.queries += 1
            self.retries += int(attempt > 1)
            response = None
            context = dict(role='receptor' if urlparse(url).hostname=='gmail.googleapis.com' else 'api_publica',
                           dataset=self.settings.gmail_campaign_tag or None, recovery='NONE')
            try:
                with self.audit.step("http_get", attempt, context=context):
                    try:
                        response = self.client.get(url, headers=headers, timeout=timeout, follow_redirects=False)
                    except httpx.TransportError as exc:
                        context['recovery'] = 'RETRY_SAFE_GET'
                        raise RPAError("HTTP_TRANSIENT") from exc
                    context['http_status'] = response.status_code
                    if response.status_code == 410:
                        raise RPAError("CURSOR_EXPIRED")
                    if urlparse(url).hostname == 'gmail.googleapis.com' and response.status_code in (401, 403):
                        from rpa.gmail_errors import error_code
                        code = error_code(response)
                        context['recovery'] = 'RETRY_SAFE_GET' if code=='GMAIL_RATE_LIMIT' else 'STOP_'+code
                        raise RPAError('HTTP_TRANSIENT' if code == 'GMAIL_RATE_LIMIT' else code)
                    if response.status_code == 429 or response.status_code >= 500:
                        context['recovery'] = 'RETRY_SAFE_GET'
                        raise RPAError("HTTP_TRANSIENT")
                    if response.status_code != 200:
                        raise RPAError(f"HTTP_{response.status_code}")
                # Éxito final distinto de intentos transitorios registrados arriba.
                self.store.execute("DELETE FROM operations WHERE execution_id=? AND op=?", (self.execution_id, key))
                return response
            except RPAError as exc:
                if exc.code != "HTTP_TRANSIENT":
                    raise
                if attempt >= self.settings.max_attempts:
                    raise RPAError("RETRIES_EXHAUSTED") from exc
                delay = retry_delay(response.headers.get("Retry-After") if response is not None else None, attempt)
                if delay >= batch_deadline - time.monotonic():
                    raise RPAError("RETRY_EXCEEDS_BUDGET")
                from rpa.store import utcnow
                waited, wait_timer = utcnow(), time.monotonic()
                self.budget.sleep(delay)
                self.audit.event('retry_wait', waited, 0, attempt=attempt, context=dict(context,
                    wait_ms=(time.monotonic()-wait_timer)*1000, recovery='RETRY_SAFE_GET'))
        raise RPAError("RETRIES_EXHAUSTED")
