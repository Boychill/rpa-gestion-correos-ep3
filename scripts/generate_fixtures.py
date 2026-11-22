"""Materializa páginas sintéticas deterministas; no requiere conexión ni credenciales."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rpa.config import Settings
from rpa.mail_read import FixtureReader


if __name__ == "__main__":
    for count in (100, 300, 500, 1000):
        reader = FixtureReader(Settings(ROOT, ROOT / "runtime", ROOT / "output", fixture_count=count))
        target = ROOT / "fixtures" / str(count)
        target.mkdir(parents=True, exist_ok=True)
        cursor, number = None, 1
        while True:
            page = reader.page(cursor)
            (target / f"page-{number:02d}.json").write_text(json.dumps(asdict(page), ensure_ascii=False, indent=2), encoding="utf-8")
            if page.phase == "DELTA":
                break
            cursor, number = page.cursor, number+1
    print("Fixtures generados: 100, 300, 500, 1000; páginas de 100.")
