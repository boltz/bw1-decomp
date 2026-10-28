#!/usr/bin/env python3
"""Report executable hash failures without exporting executable contents."""

import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re

try:
    from .decomp_binary import BinaryError, PE
except ImportError:
    from decomp_binary import BinaryError, PE

MAX_RANGES = 20
VERSIONS = ('BW1W100', 'BW1W110', 'BW1W120', 'BW1W130', 'BW1WCI')


def differences(original, built):
    """Count every different/missing byte, retaining only bounded location ranges."""
    if original == built:
        return {'different_bytes': 0, 'range_count': 0, 'ranges': []}
    count, total_ranges, start = 0, 0, None
    ranges = []
    common = min(len(original), len(built))
    for offset in range(max(len(original), len(built))):
        changed = offset >= common or original[offset] != built[offset]
        if changed:
            count += 1
            if start is None:
                start = offset
        elif start is not None:
            total_ranges += 1
            if len(ranges) < MAX_RANGES:
                ranges.append({'start': start, 'end': offset})
            start = None
    if start is not None:
        total_ranges += 1
        if len(ranges) < MAX_RANGES:
            ranges.append({'start': start, 'end': max(len(original), len(built))})
    return {'different_bytes': count, 'range_count': total_ranges, 'ranges': ranges}


def read_symbols(path):
    if path is None or not path.is_file():
        return []
    symbols = []
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.match(r'(.+?) = (\S+):0x([0-9A-Fa-f]+);.*?size:0x([0-9A-Fa-f]+)', line)
        if match:
            name, section, address, size = match.groups()
            symbols.append({'name': name, 'section': section, 'address': int(address, 16),
                            'size': int(size, 16)})
    return sorted(symbols, key=lambda symbol: symbol['address'])


def symbol_near(address, symbols, addresses):
    index = bisect.bisect_right(addresses, address) - 1
    if index < 0:
        return None
    symbol = symbols[index]
    return dict(symbol, offset=address - symbol['address'],
                relation='containing' if address < symbol['address'] + symbol['size'] else 'preceding')


def section_metadata(section):
    return {key: getattr(section, key) for key in
            ('address', 'raw_offset', 'size', 'virtual_size', 'flags')}


def section_map(image):
    counts, result = {}, {}
    for section in image.sections:
        occurrence = counts.get(section.name, 0)
        counts[section.name] = occurrence + 1
        result[(section.name, occurrence)] = section
    return result


def diagnose(original_path, built_path, symbols_path=None, expected_sha1=None):
    report = {'original': str(original_path), 'built': str(built_path), 'status': 'unavailable',
              'expected_sha1': expected_sha1, 'limitations': [], 'sections': []}
    for label, path in [('original', original_path), ('built', built_path)]:
        if not path.is_file():
            report['limitations'].append('{} executable is missing'.format(label))
    if report['limitations']:
        return report
    original, built = original_path.read_bytes(), built_path.read_bytes()
    report.update(original_sha1=hashlib.sha1(original).hexdigest(), built_sha1=hashlib.sha1(built).hexdigest(),
                  original_size=len(original), built_size=len(built),
                  file_comparison=differences(original, built), status='match' if original == built else 'different')
    if expected_sha1 and report['original_sha1'] != expected_sha1:
        report['status'] = 'original_hash_mismatch'
        report['limitations'].append('Original input does not match the configured expected SHA-1')
    symbols = read_symbols(symbols_path)
    addresses = [symbol['address'] for symbol in symbols]
    if not symbols:
        report['limitations'].append('Original symbol context is unavailable')
    try:
        left, right = PE(original), PE(built)
    except (BinaryError, ValueError) as error:
        report['limitations'].append('PE section comparison unavailable: {}'.format(error))
        return report
    report['image_bases'] = {'original': left.image_base, 'built': right.image_base}
    report['headers'] = differences(original[:left.header_size], built[:right.header_size])
    original_sections, built_sections = section_map(left), section_map(right)
    for key in dict.fromkeys([*original_sections, *built_sections]):
        a, b = original_sections.get(key), built_sections.get(key)
        row = {'name': key[0], 'occurrence': key[1],
               'original': section_metadata(a) if a else None, 'built': section_metadata(b) if b else None}
        raw_a = original[a.raw_offset:a.raw_offset + a.size] if a else b''
        raw_b = built[b.raw_offset:b.raw_offset + b.size] if b else b''
        row['comparison'] = differences(raw_a, raw_b)
        row['layout_changed'] = row['original'] != row['built']
        for span in row['comparison']['ranges']:
            start = span['start']
            span['original_va'] = a.address + start if a and start < a.size else None
            span['built_va'] = b.address + start if b and start < b.size else None
            span['original_symbol'] = (symbol_near(a.address + start, symbols, addresses)
                                       if a and start < a.size else None)
        report['sections'].append(row)
    report['limitations'].append('Ranges are end-exclusive and bounded to {} per comparison. '
                                  'Symbols describe original addresses, not proven causes. '
                                  'Section comparisons use section-relative raw bytes; virtual/BSS bytes are not synthesized.'
                                  .format(MAX_RANGES))
    return report


def render(report):
    lines = ['# Executable diagnostics', '', 'Status: **{}**'.format(report['status']), '',
             'Original: `{}`'.format(report['original']), 'Built: `{}`'.format(report['built']), '']
    if 'file_comparison' in report:
        lines += ['Original SHA-1: `{}`'.format(report['original_sha1']),
                  'Built SHA-1: `{}`'.format(report['built_sha1']),
                  'Expected SHA-1: `{}`'.format(report['expected_sha1']),
                  'File sizes: {} original, {} built.'.format(report['original_size'], report['built_size']),
                  'Different or missing file bytes: {}.'.format(report['file_comparison']['different_bytes']),
                  'First file ranges: ' + ', '.join('{:#x}–{:#x}'.format(r['start'], r['end'])
                                                   for r in report['file_comparison']['ranges']), '']
    for row in report['sections']:
        diff = row['comparison']
        lines += ['## {} [{}]'.format(row['name'], row['occurrence']), '',
                  '{} differing raw bytes; layout changed: {}.'.format(diff['different_bytes'], row['layout_changed']),
                  'Original layout: `{}`'.format(row['original']), 'Built layout: `{}`'.format(row['built']), '']
        for span in diff['ranges']:
            symbol = span['original_symbol']
            context = ('{} + {:#x} ({})'.format(symbol['name'], symbol['offset'], symbol['relation'])
                       if symbol else 'no original symbol context')
            lines.append('- Section offsets {:#x}–{:#x}; original VA {}; built VA {}; {}'.format(
                span['start'], span['end'], hex(span['original_va']) if span['original_va'] is not None else 'absent',
                hex(span['built_va']) if span['built_va'] is not None else 'absent', context))
        lines.append('')
    lines += ['## Limits', ''] + ['- ' + note for note in report['limitations']]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, choices=VERSIONS)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    manifest = Path('config') / args.version / 'build.sha1'
    records = [line.split() for line in manifest.read_text().splitlines() if line.strip()]
    built = Path('build') / args.version / 'runblack.exe'
    expected = next(digest for digest, path in records if path == built.as_posix())
    original = next(Path(path) for digest, path in records if digest == expected and path.startswith('orig/'))
    report = diagnose(original, built, manifest.with_name('symbols.txt'), expected)
    report['version'] = args.version
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (args.output_dir / 'report.md').write_text(render(report), encoding='utf-8')
    print('{}: {}'.format(args.version, report['status']))


if __name__ == '__main__':
    main()
