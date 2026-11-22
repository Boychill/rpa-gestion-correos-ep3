"""Previsualizar siempre antes de confirmar una purga. Respaldo es privado."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rpa.config import Settings
from rpa.maintenance import backup, preview, purge_events, expire_exports
from rpa.runtime import profile_lock
from rpa.store import Store


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["preview", "backup", "purge-events", "expire-exports"])
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    settings = Settings.load(ROOT)
    with profile_lock(settings.runtime / "locks/state.lock"), profile_lock(settings.runtime / "locks/cleanup.lock"), \
            Store(settings.runtime / "state.sqlite3", ROOT) as store:
        if args.action == "preview":
            result = preview(settings, store)
        elif args.action == "backup":
            path, manifest = backup(settings, store)
            result = dict(manifest, path=str(path))
        elif args.action == "purge-events":
            result = purge_events(settings, store, args.confirm)
        else:
            result = expire_exports(settings, store, args.confirm)
        print(json.dumps(result, indent=2))
