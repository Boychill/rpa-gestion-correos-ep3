"""Configuraciones y mensajes sintéticos reproducibles, sin acceso a servicios."""
from dataclasses import asdict, dataclass, field
import json
import math
import random
import re
import uuid

from rpa.runtime import RPAError

CONTENT = {
    'no_keywords': ('Sin palabras clave', 'Saludos del equipo', 'Otros'),
    'combined': ('Dos categorías', 'Consulta y reclamo de laboratorio', 'Reclamo'),
    'accents': ('Palabras con tildes', 'Información de la actividad', 'Información'),
    'mixed_case': ('Mayúsculas y minúsculas', 'uRgEnTe solicitud de acceso', 'Urgente'),
    'shared_text': ('Texto comercial repetido', 'Consulta sobre horario compartido', 'Consulta'),
}
TECHNICAL = {
    'missing_id': ('Mensaje sin ID', 'MESSAGE_ID_INVALID'),
    'invalid_date': ('Fecha inválida', 'MESSAGE_DATE_INVALID'),
    'incomplete_metadata': ('Metadatos incompletos', 'MESSAGE_METADATA_INVALID'),
    'duplicate_id': ('ID duplicado', 'DUPLICATE_DETECTED'),
    'http_429': ('HTTP 429 simulado', 'RETRIES_EXHAUSTED'),
    'http_500': ('HTTP 500 simulado', 'RETRIES_EXHAUSTED'),
    'timeout': ('Timeout simulado', 'RETRIES_EXHAUSTED'),
    'authentication': ('Autenticación simulada', 'AUTH_REQUIRED'),
    'holidays_unavailable': ('Feriados no disponibles', 'RETRIES_EXHAUSTED'),
    'supabase_failure': ('Supabase no disponible', 'LOCAL_QUEUE_PRESERVED'),
}
NORMAL = [('Solicitud de acceso', 'Solicitud'), ('Consulta sobre horario', 'Consulta'),
          ('Reclamo de laboratorio', 'Reclamo'), ('Urgente incidente simulado', 'Urgente'),
          ('Información de actividad', 'Información'), ('Saludos del equipo', 'Otros')]


@dataclass(frozen=True)
class ScenarioConfig:
    total: int = 24
    normal: int = 18
    special: int = 6
    distribution: dict = field(default_factory=lambda: {'no_keywords': 1, 'combined': 1,
        'accents': 1, 'mixed_case': 1, 'shared_text': 2})
    mode: str = 'SIMULATION'
    seed: int | None = 42
    interval: float = 1.0
    limit: int = 24

    def validate(self):
        if self.mode not in ('SIMULATION', 'GMAIL'):
            raise RPAError('SCENARIO_MODE_INVALID')
        ceiling = 500 if self.mode == 'GMAIL' else 1000
        if any(type(n) is not int or n < 0 for n in (self.total, self.normal, self.special)):
            raise RPAError('SCENARIO_QUANTITY_INVALID')
        if not 1 <= self.total <= ceiling or self.total != self.normal + self.special:
            raise RPAError('SCENARIO_TOTAL_MISMATCH')
        if not isinstance(self.distribution, dict) or any(
                key not in CONTENT and key not in TECHNICAL or type(n) is not int or n < 0
                for key, n in self.distribution.items()):
            raise RPAError('SCENARIO_DISTRIBUTION_INVALID')
        if sum(self.distribution.values()) != self.special:
            raise RPAError('SCENARIO_DISTRIBUTION_MISMATCH')
        if self.mode == 'GMAIL' and any(self.distribution.get(k, 0) for k in TECHNICAL):
            raise RPAError('TECHNICAL_SCENARIOS_LOCAL_ONLY')
        if self.seed is not None and type(self.seed) is not int:
            raise RPAError('SCENARIO_SEED_INVALID')
        if (type(self.interval) not in (int, float) or not math.isfinite(self.interval)
                or not 1 <= self.interval <= 60 or type(self.limit) is not int
                or not 1 <= self.limit <= self.total):
            raise RPAError('SCENARIO_SEND_LIMIT_INVALID')
        return self

    def to_dict(self):
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        try:
            return cls(**data).validate()
        except (TypeError, ValueError) as exc:
            raise RPAError('SCENARIO_CONFIG_INVALID') from exc


def preset(name):
    options = {'quick': (12, 3, 'SIMULATION'), 'real': (24, 6, 'GMAIL'),
               'load': (300, 60, 'SIMULATION'), 'stress': (1000, 200, 'SIMULATION')}
    if name not in options:
        raise RPAError('SCENARIO_PRESET_INVALID')
    total, special, mode = options[name]
    keys = list(CONTENT) + (list(TECHNICAL) if name in ('load', 'stress') else [])
    distribution = {key: special // len(keys) + int(i < special % len(keys))
                    for i, key in enumerate(keys)}
    if name == 'real':
        distribution = {key:2 if key=='shared_text' else 1 for key in CONTENT}
    return ScenarioConfig(total, total-special, special, distribution, mode, 42, 1.0,
                          min(total, 24)).validate()


def generate(config):
    config.validate()
    rng = random.Random(config.seed)
    kinds = ['normal'] * config.normal
    for kind in sorted(config.distribution):
        kinds.extend([kind] * config.distribution[kind])
    rng.shuffle(kinds)
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(config.to_dict(), sort_keys=True))
    rows = []
    for i, kind in enumerate(kinds, 1):
        technical = kind in TECHNICAL
        if kind == 'normal':
            subject, category = NORMAL[(i-1) % len(NORMAL)]
        elif technical:
            subject, category = 'Caso técnico sintético', None
        else:
            _, subject, category = CONTENT[kind]
        rows.append(dict(scenario_id=str(uuid.uuid5(namespace, str(i))), sequence=i,
            type=kind, special=kind != 'normal', technical=technical, subject=subject,
            expected_category=category, expected_result=TECHNICAL[kind][1] if technical else 'CLASSIFIED',
            actual_result=None, actual_category=None, validation='PENDING', failure_reason=None))
    return rows


def save_config(settings, name, config):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', name):
        raise RPAError('SCENARIO_CONFIG_NAME_INVALID')
    folder = settings.runtime / 'test_configs'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + '.json')
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
    return path


def load_config(settings, name):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', name):
        raise RPAError('SCENARIO_CONFIG_NAME_INVALID')
    try:
        return ScenarioConfig.from_dict(json.loads((settings.runtime/'test_configs'/(name+'.json')).read_text(encoding='utf-8')))
    except (OSError, ValueError) as exc:
        raise RPAError('SCENARIO_CONFIG_INVALID') from exc
