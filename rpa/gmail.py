"""Gmail OAuth y lectura metadata-only con páginas e historial. Sin lectura de cuerpos."""
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr
import hashlib
import json
from urllib.parse import urlencode, quote
import httpx

from rpa.config import timestamp
from rpa.mail_read import Page
from rpa.runtime import RPAError

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
METADATA = "https://www.googleapis.com/auth/gmail.metadata"
SEND = "https://www.googleapis.com/auth/gmail.send"


def authenticate_gmail(settings, budget, send=False):
    from rpa.gmail_auth import authorize
    return authorize(settings, budget, role='remitente' if send else 'receptor').token


class GmailReader:
    def __init__(self, settings, http, token):
        self.s, self.http, self.token = settings, http, token
        self.queries = 0
        self.refreshed = False

    def get(self, path, params=None):
        self.queries += 1
        url = BASE+path+("?"+urlencode(params, doseq=True) if params else "")
        try:
            try:
                return self.http.get(url, {"Authorization": "Bearer "+self.token}).json()
            except RPAError as exc:
                if exc.code != 'AUTH_REQUIRED' or self.refreshed:
                    raise
                self.refreshed = True
                from rpa.gmail_auth import authorize
                self.token = authorize(self.s, self.http.budget, refresh_existing=True).token
                self.queries += 1
                return self.http.get(url, {"Authorization": "Bearer "+self.token}).json()
        except ValueError as exc:
            raise RPAError("GMAIL_SCHEMA_INVALID") from exc

    def message(self, mid):
        try:
            raw = self.get("/messages/"+quote(mid, safe=""), {
                "format": "metadata", "metadataHeaders": ["Subject", "From", "Message-ID"],
                "fields": "id,internalDate,labelIds,payload/headers"})
        except RPAError as exc:
            if exc.code == "HTTP_404":
                return {"id": mid, "removed": True}
            raise
        try:
            if raw["id"] != mid:
                raise ValueError()
            if self.s.gmail_label != 'ALL' and self.s.gmail_label not in raw.get("labelIds", []):
                return {"id": mid, "removed": True}
            headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
            subject = str(make_header(decode_header(headers.get("subject", ""))))
            received = datetime.fromtimestamp(int(raw["internalDate"])/1000, timezone.utc)
            if (not timestamp(self.s.period_start) <= received < timestamp(self.s.period_end)
                    or "[RPA-EP3]" in subject.upper()
                    or (self.s.gmail_campaign_tag and self.s.gmail_campaign_tag not in subject)):
                return None
            address = parseaddr(headers.get("from", ""))[1].lower()
            return {"id": mid, "subject": subject[:2000],
                    "sender": "anon-"+hashlib.sha256(address.encode()).hexdigest()[:12],
                    "received": received.isoformat(), "modified": "gmail-metadata-v2",
                    "rfc_message_id": headers.get("message-id", "")[:300]}
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            raise RPAError("GMAIL_SCHEMA_INVALID") from exc

    def page(self, cursor=None):
        try:
            state = json.loads(cursor) if cursor else {"mode": "full"}
            mode = state["mode"]
            if mode not in {"full", "history"}:
                raise ValueError()
            if mode == "full":
                # Leer el historyId ANTES del escaneo permite recuperar cambios durante la paginación.
                base_history = state.get("history") or self.get("/profile")["historyId"]
                params = {"maxResults": self.s.gmail_batch_size,
                          "q": f'after:{int(timestamp(self.s.period_start).timestamp())} before:{int(timestamp(self.s.period_end).timestamp())} -subject:"[RPA-EP3]"'}
                if self.s.gmail_label == 'ALL':
                    params['includeSpamTrash'] = 'true'
                else:
                    params['labelIds'] = self.s.gmail_label
                if self.s.gmail_campaign_tag:
                    params['q'] += ' subject:"'+self.s.gmail_campaign_tag+'"'
                if state.get("page"):
                    params["pageToken"] = state["page"]
                raw = self.get("/messages", params)
                ids = [r["id"] for r in raw.get("messages", [])]
                removed = []
                next_state = {"mode": "full", "history": base_history, "page": raw.get("nextPageToken")}
            else:
                base_history = state["history"]
                params = {"startHistoryId": base_history, "maxResults": self.s.gmail_batch_size}
                if self.s.gmail_label != 'ALL':
                    params['labelId'] = self.s.gmail_label
                if state.get("page"):
                    params["pageToken"] = state["page"]
                try:
                    raw = self.get("/history", params)
                except RPAError as exc:
                    if exc.code == "HTTP_404":
                        raise RPAError("CURSOR_EXPIRED") from exc
                    raise
                ids, removed = [], []
                for change in raw.get("history", []):
                    for name in ("messagesAdded", "labelsAdded", "labelsRemoved"):
                        ids.extend(r["message"]["id"] for r in change.get(name, []))
                    removed.extend(r["message"]["id"] for r in change.get("messagesDeleted", []))
                next_state = {"mode": "history", "history": base_history, "page": raw.get("nextPageToken")}
            messages = []
            deleted = set(removed)
            for mid in dict.fromkeys(ids):
                if mid not in deleted:
                    item = self.message(mid)
                    if item is not None:
                        messages.append(item)
            messages.extend({"id": mid, "removed": True} for mid in deleted)
            if raw.get("nextPageToken"):
                return Page(messages, json.dumps(next_state), "NEXT")
            if mode == "full":
                # No cerrar aún: recorrer el historial posterior al inicio del escaneo.
                return Page(messages, json.dumps({"mode": "history", "history": base_history}), "NEXT")
            return Page(messages, json.dumps({"mode": "history", "history": raw["historyId"]}), "DELTA")
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise RPAError("GMAIL_SCHEMA_INVALID") from exc
