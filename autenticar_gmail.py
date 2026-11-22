"""Autorización inicial explícita, separada de cualquier envío."""
import argparse
import json
from pathlib import Path
from rpa.config import Settings
from rpa.gmail_auth import authorize_with_audit
from rpa.runtime import Budget, RPAError

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rol', choices=['remitente', 'receptor'])
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    settings = Settings.load(Path(__file__).resolve().parent)
    account = settings.gmail_sender_address if args.rol == 'remitente' else settings.gmail_receiver_address
    print('Selecciona la cuenta '+account+' para el rol '+args.rol+'.', flush=True)
    try:
        authorize_with_audit(settings, args.rol, force=args.force)
        print(json.dumps({'status':'AUTHORIZED', 'role':args.rol,
                          'identity_verified':args.rol=='receptor'}))
    except RPAError as exc:
        print(json.dumps({'status':'FAILED', 'code':exc.code}))
        raise SystemExit(1)
