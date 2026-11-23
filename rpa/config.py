"""Entrada: .env y entorno. Salida: Settings validado. Error: ValueError."""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import re
from urllib.parse import urlparse


def timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("FECHA_SIN_ZONA")
    return dt


@dataclass(frozen=True)
class Settings:
    root: Path
    runtime: Path
    output: Path
    source: str = "FIXTURE"
    fixture_count: int = 100
    holiday_mode: str = "FIXTURE"
    mail_mode: str = "DRY_RUN"
    mail_adapter: str = "OUTLOOK"
    profile: str = "demo"
    batch_size: int = 100
    graph_page_size: int = 100
    period_start: str = "2026-01-01T00:00:00Z"
    period_end: str = "2027-01-01T00:00:00Z"
    business_days: int = 3
    max_attempts: int = 3
    http_timeout: float = 20
    batch_seconds: float = 60
    execution_seconds: float = 600
    cache_hours: float = 168
    require_excel: bool = False
    tenant_id: str = ""
    client_id: str = ""
    mailbox: str = ""
    folder_id: str = "inbox"
    send_authorized: bool = False
    recipient: str = ""
    allowed_recipients: str = ""
    retention_debug_days: int = 7
    retention_info_days: int = 15
    retention_error_days: int = 30
    retention_export_days: int = 7
    analytics_retention_days: int = 90
    supabase_enabled: bool = False
    supabase_context_enabled: bool = False
    supabase_url: str = ""
    supabase_secret_key: str = field(default="", repr=False)
    log_sync_batch_size: int = 100
    log_sync_max_batches: int = 5
    log_sync_max_attempts: int = 3
    log_sync_seconds: float = 30
    log_download_days: int = 15
    auto_clean_logs: bool = True
    log_cleanup_interval_seconds: int = 3600
    gmail_client_file: str = "config/google/credentials.json"
    gmail_sender_token_path: str = "config/google/token_remitente.json"
    gmail_receiver_token_path: str = "config/google/token_receptor.json"
    gmail_sender_address: str = ""
    gmail_receiver_address: str = ""
    gmail_batch_size: int = 100
    oauth_timeout_seconds: float = 180
    display_timezone: str = "America/Santiago"
    gmail_label: str = "INBOX"
    gmail_campaign_tag: str = ""

    @classmethod
    def load(cls, root):
        root = Path(root).resolve()
        env = {}
        path = root / ".env"
        if path.exists():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                if line.strip() and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip().strip('"').strip("'")
        env.update(os.environ)
        aliases = {'GMAIL_CREDENTIALS_PATH': 'GMAIL_CLIENT_FILE', 'HTTP_TIMEOUT_SECONDS': 'HTTP_TIMEOUT',
                   'RUN_DEADLINE_SECONDS': 'EXECUTION_SECONDS', 'REPORT_TO': 'RECIPIENT'}
        for key, target in aliases.items():
            if key in env and (key in os.environ or target not in os.environ):
                env[target] = env[key]
        if env.get('MAIL_PROVIDER', '').lower() == 'gmail':
            if 'MAIL_ADAPTER' not in os.environ:
                env['MAIL_ADAPTER'] = 'GMAIL'
            if env.get('SOURCE') == 'GMAIL':
                env['MAILBOX'] = env.get('GMAIL_RECEIVER_ADDRESS', env.get('MAILBOX', ''))
        values = {"root": root, "runtime": (root / env.get("RUNTIME_DIR", "runtime")).resolve(),
                  "output": (root / env.get("OUTPUT_DIR", "output")).resolve()}
        for name, field in cls.__dataclass_fields__.items():
            if name in values or name.upper() not in env:
                continue
            raw = env[name.upper()]
            if field.type is bool:
                if raw.lower() not in {"true", "false"}:
                    raise ValueError("BOOLEANO_INVALIDO")
                values[name] = raw.lower() == "true"
            else:
                values[name] = field.type(raw)
        result = cls(**values)
        result.validate()
        return result

    def validate(self):
        if self.source not in {"FIXTURE", "GRAPH", "GMAIL"} or self.holiday_mode not in {"FIXTURE", "LIVE"}:
            raise ValueError("MODO_ORIGEN_INVALIDO")
        if self.mail_mode not in {"DRY_RUN", "SEND"} or self.mail_adapter not in {"OUTLOOK", "GRAPH", "GMAIL"}:
            raise ValueError("MODO_CORREO_INVALIDO")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", self.profile):
            raise ValueError("PERFIL_INVALIDO")
        if timestamp(self.period_start) >= timestamp(self.period_end):
            raise ValueError("PERIODO_INVALIDO")
        for name in ("batch_size", "graph_page_size", "max_attempts", "http_timeout", "batch_seconds",
                     "execution_seconds", "cache_hours", "retention_debug_days", "retention_info_days",
                     "retention_error_days", "retention_export_days", "analytics_retention_days"):
            if getattr(self, name) <= 0:
                raise ValueError("LIMITE_INVALIDO")
        if not 1 <= self.business_days <= 30 or not 0 <= self.fixture_count <= 100000:
            raise ValueError("CANTIDAD_INVALIDA")
        if self.graph_page_size > 1000 or self.max_attempts > 10:
            raise ValueError("LIMITE_EXCESIVO")
        if not (1 <= self.log_sync_batch_size <= 500 and 1 <= self.log_sync_max_batches <= 20
                and 1 <= self.log_sync_max_attempts <= 3 and self.log_sync_seconds > 0
                and self.log_download_days >= 1 and self.log_cleanup_interval_seconds >= 60):
            raise ValueError("LOG_CONFIG_INVALID")
        if self.supabase_url:
            url = urlparse(self.supabase_url)
            if (url.scheme != "https" or not url.hostname or url.username or url.password
                    or url.query or url.fragment or url.path not in {"", "/"}):
                raise ValueError("SUPABASE_URL_INVALID")
        if self.supabase_enabled and not (self.supabase_url and self.supabase_secret_key.startswith("sb_secret_")):
            raise ValueError("SUPABASE_CONFIG_REQUIRED")
        if self.source == "GRAPH" and not (self.client_id and self.tenant_id and self.mailbox):
            raise ValueError("FALTA_CONFIG_GRAPH")
        if self.source == "GMAIL" and (not self.mailbox or not self.gmail_label):
            raise ValueError("FALTA_CONFIG_GMAIL")
        if (self.source == 'GMAIL' and self.gmail_receiver_address
                and self.mailbox.lower() != self.gmail_receiver_address.lower()):
            raise ValueError('GMAIL_RECEIVER_MISMATCH')
        if not 1 <= self.gmail_batch_size <= 500 or not 0 < self.oauth_timeout_seconds <= 300:
            raise ValueError('GMAIL_LIMIT_INVALID')
        for address in (self.gmail_sender_address, self.gmail_receiver_address):
            if address and not re.fullmatch(r'[^\s@;,<>]+@[^\s@;,<>]+\.[^\s@;,<>]+', address):
                raise ValueError('GMAIL_ADDRESS_INVALID')
        if self.gmail_campaign_tag and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.gmail_campaign_tag):
            raise ValueError('GMAIL_DATASET_INVALID')
        if self.source=='GMAIL' and self.gmail_label=='ALL' and not self.gmail_campaign_tag:
            raise ValueError('GMAIL_ALL_REQUIRES_DATASET')
        if self.mail_mode == "SEND":
            allowed = {a.strip().lower() for a in self.allowed_recipients.split(",") if a.strip()}
            provider_ok = (self.source == 'GRAPH' and self.mail_adapter in {'GRAPH', 'OUTLOOK'}
                           or self.source == 'GMAIL' and self.mail_adapter == 'GMAIL' and self.gmail_sender_address)
            if (not self.send_authorized or not provider_ok or self.holiday_mode != "LIVE"
                    or (self.source == 'GRAPH' and not self.require_excel) or not self.mailbox
                    or not re.fullmatch(r"[^\s@;,<>]+@[^\s@;,<>]+\.[^\s@;,<>]+", self.recipient)
                    or self.recipient.lower() not in allowed):
                raise ValueError("ENVIO_NO_AUTORIZADO")

    @property
    def scope(self):
        values = [self.source, self.mailbox.lower(), self.folder_id, self.period_start,
                  self.period_end, self.fixture_count if self.source == "FIXTURE" else None]
        if self.source == "GMAIL":
            values.extend([self.gmail_label, self.gmail_campaign_tag])
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    @property
    def identity(self):
        return f"{self.source}:{self.mailbox.lower() if self.source in {'GRAPH', 'GMAIL'} else 'synthetic'}"

    @property
    def signature(self):
        values = [self.scope, self.holiday_mode, self.mail_mode, self.mail_adapter, self.recipient,
                  self.business_days, self.require_excel,
                  hashlib.sha256((self.root / "config/reglas.json").read_bytes()).hexdigest()]
        if self.source == 'GMAIL':
            values.extend([self.gmail_sender_address.lower(), self.gmail_receiver_address.lower()])
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()
