"""Preparar o enviar una copia del consolidado mediante la misma l?gica que la interfaz."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rpa.config import Settings
from rpa.campaign_report import export_campaign
from rpa.report_actions import preview_report, deliver_report
from rpa.runtime import RPAError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',required=True)
    parser.add_argument('--recipient',required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    settings=Settings.load(Path(__file__).resolve().parents[1])
    report=export_campaign(settings,args.campaign)
    preview=preview_report(settings,report['execution_id'],args.recipient)
    if args.execute:
        result=deliver_report(settings,preview,execute=True)
        print(json.dumps(result,indent=2))
        return 0 if result['send_state'] in ('ACEPTADO','ENTREGA_CONFIRMADA') else 1
    preview.pop('body')
    print(json.dumps(dict(preview,mail_mode='DRY_RUN'),indent=2))
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (RPAError,ValueError) as exc:
        print(exc.code if isinstance(exc,RPAError) else 'CONFIG_INVALID')
        raise SystemExit(1)
