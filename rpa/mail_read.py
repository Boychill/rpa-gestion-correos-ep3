"""Entrada: ámbito, cursor opaco y OAuth. Salida: Page mínimo. Errores: RPAError."""
from dataclasses import dataclass
from datetime import timedelta
import hashlib
from urllib.parse import quote, urlencode, urlparse
import msal

from rpa.config import timestamp
from rpa.runtime import RPAError


@dataclass
class Page:
    messages: list
    cursor: str
    phase: str


def authenticate(settings, budget):
    # TokenCache solo en memoria; no se guardan tokens/refresh tokens en disco.
    app = msal.PublicClientApplication(settings.client_id,
          authority=f"https://login.microsoftonline.com/{quote(settings.tenant_id, safe='')}")
    scopes = ["Mail.ReadBasic"]
    if settings.mail_mode == "SEND" and settings.mail_adapter == "GRAPH":
        scopes.append("Mail.Send")
    result = app.acquire_token_interactive(scopes=scopes, login_hint=settings.mailbox,
                                           timeout=min(180, budget.remaining()))
    if "access_token" not in result:
        raise RPAError("OAUTH_FAILED")
    claims = result.get("id_token_claims", {})
    account = claims.get("preferred_username", claims.get("email", ""))
    if account.lower() != settings.mailbox.lower():
        raise RPAError("OAUTH_ACCOUNT_MISMATCH")
    return result["access_token"]


def safe_graph_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com"
            or not parsed.path.startswith("/v1.0/") or parsed.fragment):
        raise RPAError("UNTRUSTED_GRAPH_LINK")
    return url


class GraphReader:
    def __init__(self, settings, http, token):
        self.s, self.http, self.token = settings, http, token
        self.queries = 0

    def page(self, cursor=None):
        url = cursor or ("https://graph.microsoft.com/v1.0/me/mailFolders/"
              + quote(self.s.folder_id, safe="") + "/messages/delta?" + urlencode({
                  "$select": "id,subject,from,receivedDateTime,lastModifiedDateTime",
                  "$top": self.s.graph_page_size,
                  "$filter": "receivedDateTime ge " + self.s.period_start}))
        self.queries += 1
        response = self.http.get(safe_graph_url(url), {
            "Authorization": "Bearer " + self.token, "Prefer": 'IdType="ImmutableId"'})
        try:
            data = response.json()
            if not isinstance(data["value"], list):
                raise ValueError()
            next_link, delta_link = data.get("@odata.nextLink"), data.get("@odata.deltaLink")
            if bool(next_link) == bool(delta_link):
                raise ValueError()
            link = safe_graph_url(next_link or delta_link)
            messages = []
            for raw in data["value"]:
                mid = raw["id"]
                if not isinstance(mid, str) or not mid:
                    raise ValueError()
                if "@removed" in raw:
                    messages.append({"id": mid, "removed": True})
                    continue
                # No aceptar silenciosamente un cambio parcial que podría perder metadatos.
                received = timestamp(raw["receivedDateTime"])
                subject = raw.get("subject") or ""
                if not isinstance(subject, str):
                    raise ValueError()
                if not timestamp(self.s.period_start) <= received < timestamp(self.s.period_end):
                    continue
                if "[RPA-EP3]" in subject.upper():
                    continue
                sender = (raw.get("from") or {}).get("emailAddress", {}).get("address", "")
                # Solo conservar seudónimo; no son necesarios los remitentes originales.
                sender_hash = hashlib.sha256(sender.lower().encode()).hexdigest()[:12]
                messages.append({"id": mid, "subject": subject[:2000], "sender": "anon-" + sender_hash,
                                 "received": received.isoformat(), "modified": raw.get("lastModifiedDateTime", "")})
            return Page(messages, link, "NEXT" if next_link else "DELTA")
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise RPAError("GRAPH_SCHEMA_INVALID") from exc


class FixtureReader:
    def __init__(self, settings):
        self.s, self.queries = settings, 0

    def page(self, cursor=None):
        self.queries += 1
        if cursor == "fixture:done":
            return Page([], "fixture:done", "DELTA")
        offset = int(cursor.split(":")[1]) if cursor else 0
        subjects = ["Solicitud de certificado", "Consulta sobre horario", "Reclamo por demora",
                    "URGENTE: solicitud crítica", "Información de servicio", "", "=1+1", "consulta y reclamo"]
        end = min(offset + self.s.graph_page_size, self.s.fixture_count)
        start = timestamp(self.s.period_start)
        span = (timestamp(self.s.period_end)-start).total_seconds()
        messages = [{"id": f"fixture-{i:06d}", "subject": subjects[i % len(subjects)],
                     "sender": f"anon-fixture-{i % 31:02d}",
                     "received": (start + timedelta(seconds=(i*3600) % span)).isoformat(),
                     "modified": "fixture-v1"} for i in range(offset, end)]
        return Page(messages, f"fixture:{end}" if end < self.s.fixture_count else "fixture:done",
                    "NEXT" if end < self.s.fixture_count else "DELTA")
