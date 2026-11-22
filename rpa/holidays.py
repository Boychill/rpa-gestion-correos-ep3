"""Entrada: país CL/año. Salida: feriados validados y procedencia. Fallo: plazo nulo."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json

from rpa.config import timestamp
from rpa.runtime import RPAError
from rpa.store import utcnow


def validate_holidays(data, year):
    if not isinstance(data, list) or not data:
        raise RPAError("HOLIDAY_SCHEMA_INVALID")
    try:
        for item in data:
            day = date.fromisoformat(item["date"])
            if (day.year != year or item["countryCode"] != "CL" or not isinstance(item["localName"], str)
                    or not isinstance(item["global"], bool) or not isinstance(item["types"], list)):
                raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise RPAError("HOLIDAY_SCHEMA_INVALID") from exc
    return data


class Holidays:
    def __init__(self, settings, http):
        self.s, self.http = settings, http
        self.loaded, self.errors = {}, {}

    def year(self, year):
        if year in self.errors:
            raise RPAError(self.errors[year])
        if year in self.loaded:
            return self.loaded[year]
        try:
            result = self._load(year)
            self.loaded[year] = result
            return result
        except RPAError as exc:
            self.errors[year] = exc.code
            raise

    def _load(self, year):
        if self.s.holiday_mode == "FIXTURE":
            # Calendario sintético incompleto por diseño; nunca se etiqueta como calendario real.
            values = [{"date": f"{year}-{day}", "localName": name, "countryCode": "CL",
                       "global": True, "types": ["Public"]}
                      for day, name in [("01-01", "Fixture Año Nuevo"), ("05-01", "Fixture Trabajo"),
                                        ("09-18", "Fixture Fiestas"), ("12-25", "Fixture Navidad")]]
            return {"data": values, "origin": "fixture", "provider": "synthetic", "http_status": None,
                    "queried": utcnow(), "country": "CL", "year": year}
        cache = self.s.runtime / "cache" / f"CL-{year}.json"
        if cache.exists():
            try:
                value = json.loads(cache.read_text(encoding="utf-8"))
                age = (datetime.now(timezone.utc)-timestamp(value["queried"])).total_seconds()/3600
                validate_holidays(value["data"], year)
                if (0 <= age < self.s.cache_hours and value["country"] == "CL"
                        and value["year"] == year and value["provider"] == "Nager.Date"):
                    return dict(value, origin="cache")
            except (ValueError, KeyError, RPAError):
                pass
        response = self.http.get(f"https://date.nager.at/api/v3/PublicHolidays/{year}/CL")
        try:
            values = validate_holidays(response.json(), year)
        except ValueError as exc:
            raise RPAError("HOLIDAY_SCHEMA_INVALID") from exc
        value = {"data": values, "origin": "real", "provider": "Nager.Date", "http_status": response.status_code,
                 "queried": utcnow(), "country": "CL", "year": year}
        cache.parent.mkdir(parents=True, exist_ok=True)
        temp = cache.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temp.replace(cache)
        return value

    def due(self, received):
        day = timestamp(received).astimezone(ZoneInfo("America/Santiago")).date()
        remaining = self.s.business_days
        try:
            # Día de recepción no cuenta. Solo feriados nacionales Public; sin feriados regionales.
            while remaining:
                day += timedelta(days=1)
                data = self.year(day.year)
                holidays = {date.fromisoformat(h["date"]) for h in data["data"]
                            if h["global"] and "Public" in h["types"]}
                if day.weekday() < 5 and day not in holidays:
                    remaining -= 1
            return day.isoformat(), "OK"
        except RPAError as exc:
            return None, exc.code

    def apply(self, items):
        for item in items:
            item["due"], item["due_result"] = self.due(item["received"])
        return items
