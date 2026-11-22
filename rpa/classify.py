"""Entrada: asunto y reglas confiables. Salida: categoría/regla/versión. Error: ValueError."""
import json
import re
import unicodedata

CATEGORIES = ("Solicitud", "Consulta", "Reclamo", "Urgente", "Información", "Otros")


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(c)).casefold()


class Classifier:
    def __init__(self, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.version = data["version"]
        self.rules = []
        ids, priorities = set(), set()
        for rule in data["rules"]:
            if (rule["category"] not in CATEGORIES[:-1] or rule["id"] in ids
                    or rule["priority"] in priorities or not rule.get("keywords")
                    or not isinstance(rule["priority"], int)):
                raise ValueError("REGLA_INVALIDA")
            ids.add(rule["id"])
            priorities.add(rule["priority"])
            # Regex generada a partir de palabras literales: sin ejecución de regex arbitraria.
            if any(not isinstance(k, str) or not k.strip() or len(k) > 80 for k in rule["keywords"]):
                raise ValueError("PALABRA_INVALIDA")
            pattern = re.compile(r"\b(?:" + "|".join(re.escape(normalize(k)) for k in rule["keywords"]) + r")\b")
            self.rules.append((rule["priority"], rule["id"], rule["category"], pattern))
        self.rules.sort(key=lambda r: r[0])

    def classify(self, subject):
        text = normalize(subject)
        for _, rule, category, pattern in self.rules:
            if pattern.search(text):
                return category, rule, self.version
        return "Otros", "fallback", self.version
