"""Genera el consolidado completo del dataset; nunca envía mensajes."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rpa.config import Settings
from rpa.campaign_report import export_campaign
from rpa.runtime import RPAError

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(export_campaign(Settings.load(Path(__file__).resolve().parents[1]),args.campaign),indent=2))
    except RPAError as exc:
        print(exc.code)
        raise SystemExit(1)
