"""Punto de entrada estable: las rutas internas parten de este archivo, no del cwd."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

from rpa.config import Settings
from rpa.runtime import RPAError


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Robot EP3 de gestión de correos")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="Ejecutar o reanudar el flujo")
    run_parser.add_argument("--resume")
    run_parser.add_argument("--count", type=int)
    sub.add_parser("init", help="Crear plantilla si no existe")
    sub.add_parser("logs-sync", help="Sincronizar logs con Supabase; máximo tres intentos persistentes")
    sub.add_parser("logs-clean", help="Aplicar la retención configurada de archivos de log")
    logs = sub.add_parser("logs-download", help="Guardar copia local .log desde SQLite o Supabase")
    logs.add_argument("--execution-id")
    logs.add_argument("--source", choices=["LOCAL", "SUPABASE"], default="LOCAL")
    panel = sub.add_parser("panel", help="Panel solo en 127.0.0.1")
    panel.add_argument("--port", type=int, default=8000)
    reconcile_parser = sub.add_parser("reconcile", help="Registrar verificación manual sin reenviar")
    reconcile_parser.add_argument("execution_id")
    reconcile_parser.add_argument("--state", choices=["ACEPTADO", "ENTREGA_CONFIRMADA"], required=True)
    reconcile_parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.load(root)
    if args.command == "init":
        from rpa.excel import create_template
        create_template(root / "templates/reporte_base.xlsx")
        print("Plantilla disponible. Envíos deshabilitados por defecto.")
    elif args.command == "run":
        from rpa.orchestrator import run
        if args.count is not None:
            settings = replace(settings, fixture_count=args.count)
        result = run(settings, args.resume)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"COMPLETED", "NO_CHANGES", "DRY_RUN", "ACEPTADO", "ENTREGA_CONFIRMADA"} else 2
    elif args.command == "panel":
        import uvicorn
        from rpa.panel import create_app
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, access_log=False)
    elif args.command.startswith("logs-"):
        from rpa.cloud_logs import sync_logs, fetch_cloud_logs, log_records
        from rpa.log_files import save_log, auto_cleanup
        from rpa.runtime import profile_lock
        from rpa.store import Store
        with profile_lock(settings.runtime / "locks/state.lock"), Store(settings.runtime / "state.sqlite3", root) as store:
            if args.command == "logs-sync":
                result = sync_logs(settings, store)
            elif args.command == "logs-clean":
                result = auto_cleanup(settings, store)
            else:
                if args.execution_id and not store.row("SELECT id FROM executions WHERE id=?", (args.execution_id,)):
                    raise RPAError("EXECUTION_NOT_FOUND")
                records = (fetch_cloud_logs(settings, store, args.execution_id) if args.source == "SUPABASE"
                           else log_records(store, args.execution_id))
                result = save_log(settings, store, records, args.source, args.execution_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        from rpa.mail_send import reconcile
        from rpa.runtime import profile_lock
        from rpa.store import Store
        with profile_lock(settings.runtime / "locks" / f"{settings.profile}.lock"), Store(settings.runtime / "state.sqlite3", root) as store:
            reconcile(store, args.execution_id, args.state, args.evidence.resolve())
        print("Reconciliación registrada. No se envió correo.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RPAError, ValueError) as exc:
        print(json.dumps({"error": exc.code if isinstance(exc, RPAError) else "CONFIG_INVALID"}))
        sys.exit(2)
