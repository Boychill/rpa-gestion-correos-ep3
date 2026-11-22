"""Simulación de escenarios sin red ni envíos de correo."""
from dataclasses import replace
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rpa.config import Settings
from rpa.demo_actions import DemoActions
from rpa.runtime import RPAError
from rpa.scenarios import ScenarioConfig, preset


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    choice=parser.add_mutually_exclusive_group()
    choice.add_argument('--preset',choices=['quick','load','stress'],default='quick')
    choice.add_argument('--config',type=Path)
    parser.add_argument('--seed',type=int)
    args=parser.parse_args()
    config=ScenarioConfig.from_dict(json.loads(args.config.read_text(encoding='utf-8'))) if args.config else preset(args.preset)
    if args.seed is not None:config=replace(config,seed=args.seed)
    result=DemoActions(Settings.load(Path(__file__).resolve().parents[1])).simulation(config)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['validation_status']=='PASSED' and result['status'] in ('COMPLETED','NO_CHANGES') else 1


if __name__=='__main__':
    try:sys.exit(main())
    except (RPAError,ValueError) as exc:
        print(exc.code if isinstance(exc,RPAError) else 'SCENARIO_CONFIG_INVALID');sys.exit(1)
