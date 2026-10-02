#!/usr/bin/env python3
"""Check authoritative config selection, PRIVATE storage and selected channel resources."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import config
from scripts.capabilities import doctor


def discover(override):
    root = config.find_config_dir(override)
    return str(root), 'authoritative config selection'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--channel')
    args = parser.parse_args()
    try:
        result = doctor(config.load(args.config_dir), channel=args.channel)
    except config.ConfigError as exc:
        result = {'status': 'not_ready', 'checks': [{'name': 'selected config and PRIVATE DATA boundary',
                  'ok': False, 'reason': str(exc)}], 'live_proven': 'not_run'}
    print(json.dumps(result, ensure_ascii=False))
    return int(result['status'] != 'ready')


if __name__ == '__main__':
    raise SystemExit(main())
