"""Autoriza una cuenta sin enviar mensajes; tokens protegidos con DPAPI en Windows."""
from pathlib import Path
import argparse
from dataclasses import replace
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rpa.config import Settings
from rpa.gmail_auth import authorize
from rpa.runtime import Budget, RPAError

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account', required=True)
    parser.add_argument('--send', action='store_true')
    parser.add_argument('--force', action='store_true', help='Reautorizar explícitamente una cuenta o token vencido')
    args = parser.parse_args()
    settings = replace(Settings.load(Path(__file__).resolve().parents[1]), mailbox=args.account,
                       **{'gmail_sender_address' if args.send else 'gmail_receiver_address': args.account})
    try:
        authorize(settings, Budget(240), 'remitente' if args.send else 'receptor', interactive=True, force=args.force)
        print('GMAIL_AUTHORIZED: '+args.account)
        if args.send:
            print('SEND_ONLY: cuenta seleccionada por el usuario; identidad pendiente de contrastar en recepción.')
    except RPAError as exc:
        print(exc.code)
        sys.exit(1)
