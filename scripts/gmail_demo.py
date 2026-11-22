"""Preparar, enviar y analizar un lote Gmail; ejecutar desde cualquier directorio."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rpa.config import Settings
from rpa.gmail_campaign import prepare, send, analyze, summary, load
from rpa.runtime import RPAError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--sender', required=True)
    p.add_argument('--recipient', required=True)
    p.add_argument('--count', type=int, required=True)
    for command in ('send', 'analyze', 'status', 'run'):
        p = sub.add_parser(command)
        p.add_argument('--campaign', required=True)
        if command in ('send', 'run'):
            p.add_argument('--sender', required=True)
            p.add_argument('--recipient', required=True)
            p.add_argument('--count', type=int, required=True)
            p.add_argument('--execute', action='store_true', help='Enviar realmente; por defecto solo simulación')
            p.add_argument('--limit', type=int, help='Máximo de mensajes de este lote a intentar en esta invocación')
    args = parser.parse_args()
    settings = Settings.load(Path(__file__).resolve().parents[1])
    if args.command=='prepare':
        result = prepare(settings, args.sender, args.recipient, args.count)
        result.pop('messages')
    elif args.command in ('send', 'run'):
        if load(settings, args.campaign)['count'] != args.count:
            raise RPAError('CAMPAIGN_COUNT_MISMATCH')
        if args.command=='run' and args.execute:
            # Autorizar la lectura antes de comenzar a enviar.
            from dataclasses import replace
            from rpa.gmail import authenticate_gmail
            from rpa.runtime import Budget
            authenticate_gmail(replace(settings, mailbox=args.recipient), Budget(240))
        result = send(settings, args.campaign, args.sender, args.recipient, execute=args.execute, limit=args.limit)
        if args.command=='run' and args.execute and result['accepted']:
            result = {'send': result, 'analysis': analyze(settings, args.campaign)}
    elif args.command=='analyze':
        result = analyze(settings, args.campaign)
    else:
        result = summary(settings, args.campaign)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get('error') or (args.command=='analyze' and not result.get('complete')):
        return 1
    if args.command in ('send', 'run') and args.execute and not result.get('send', result).get('all_accepted'):
        return 1
    if args.command=='run' and args.execute and result.get('analysis') and not result['analysis']['complete']:
        return 1
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except RPAError as exc:
        print(exc.code)
        sys.exit(1)
