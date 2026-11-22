"""Pruebas reales sin buzón: GET público y apertura de copia sintética en Excel COM."""
from pathlib import Path
import json
import platform
import shutil
import sys
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rpa.config import Settings
from rpa.excel import desktop_excel, create_template, file_hash
from rpa.holidays import validate_holidays
from rpa.store import utcnow


def main():
    target = ROOT / "docs/evidence"
    target.mkdir(parents=True, exist_ok=True)
    result = {"checked_at": utcnow(), "platform": platform.platform(), "graph": "NO_PROBADO_SIN_BUZON_AUTORIZADO",
              "mail_send": "NO_EJECUTADO", "api": [], "excel": {}, "outlook": {}}
    with httpx.Client(timeout=20) as client:
        for year in (2026, 2027):
            url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/CL"
            try:
                response = client.get(url)
                response.raise_for_status()
                values = validate_holidays(response.json(), year)
                evidence = {"provider": "Nager.Date", "year": year, "url": url, "status": response.status_code,
                            "origin": "real", "queried": utcnow(), "count": len(values), "data": values}
                (target / f"api_CL_{year}.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
                result["api"].append({"year": year, "status": "VERIFICADO", "http": response.status_code, "count": len(values)})
            except Exception as exc:
                result["api"].append({"year": year, "status": "NO_VERIFICADO", "error": type(exc).__name__})
    settings = Settings(root=ROOT, runtime=ROOT / "runtime", output=ROOT / "output")
    template = ROOT / "templates/reporte_base.xlsx"
    create_template(template)
    copy = settings.output / "verificacion escritorio" / "copia plantilla.xlsx"
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, copy)
    before = file_hash(copy)
    try:
        data = desktop_excel(settings, copy, 40)
        result["excel"] = dict(data, before_hash=before, after_hash=file_hash(copy))
    except Exception as exc:
        result["excel"] = {"status": "NO_VERIFICADO", "error": getattr(exc, "code", type(exc).__name__)}
    if sys.platform == "win32":
        import winreg
        for program in ("Excel.Application", "Outlook.Application"):
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, program + "\\CLSID"):
                    registered = True
            except OSError:
                registered = False
            result["outlook" if program.startswith("Outlook") else "excel"]["com_registered"] = registered
    (target / "real_checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
