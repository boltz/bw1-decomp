#!/usr/bin/env python3
"""Collect bounded, read-only objdiff evidence from CI's freshly built objects."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from decomp_common import load_project


def collect(base, head, version):
    changed = subprocess.check_output(
        ['git', 'diff', '--name-only', base, head], text=True
    ).splitlines()
    headers_changed = any(path.endswith(('.h', '.hpp', '.inc')) for path in changed)
    project_units = load_project()['units']
    direct = [unit for unit in project_units
              if unit.get('metadata', {}).get('source_path') in changed]
    consumers = [unit for unit in project_units if unit not in direct] if headers_changed else []
    units = direct + consumers
    result = {'version': version, 'base_sha': base, 'head_sha': head,
              'mode': 'strict object comparison, functionRelocDiffs=all',
              'compiled_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'scope': 'all units (header changed)' if headers_changed else 'changed source units',
              'limitations': [], 'units': []}
    if len(units) > 8:
        result['limitations'].append('Unit limit: {} of {} selected units included'.format(8, len(units)))
    output_limit = 20_000 // max(1, min(8, len(units))) // 2
    for unit in units[:8]:
        entry = {'name': unit['name'], 'source': unit.get('metadata', {}).get('source_path'),
                 'metadata': unit.get('metadata', {})}
        for label, args in [('summary', ['--sections']),
                            ('disassembly', ['-d', '.*', '--regex', '--range', '0-200'])]:
            try:
                run = subprocess.run(
                    [sys.executable, 'tools/decomp-diff.py', '--unit', unit['name'], '--strict'] + args,
                    capture_output=True, text=True, timeout=45)
                entry[label] = run.stdout[:output_limit]
                if run.returncode:
                    result['limitations'].append('{} {} failed: {}'.format(
                        unit['name'], label, run.stderr[:1000]))
                if len(run.stdout) > output_limit:
                    result['limitations'].append('{} {} truncated'.format(unit['name'], label))
            except subprocess.TimeoutExpired:
                result['limitations'].append('{} {} timed out'.format(unit['name'], label))
        result['units'].append(entry)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.base, args.head, args.version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
