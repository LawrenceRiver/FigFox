"""Portable local SVG tools for the FigFox skill; no provider/network calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
from native_edits import apply_edits, safe_svg, validate_implementation

OPERATIONS = {'set', 'text', 'remove', 'append_svg', 'replace_svg', 'source_crop'}


def load_svg(path):
    text = Path(path).read_text(encoding='utf-8')
    root = ET.fromstring(text)
    if root.tag != '{http://www.w3.org/2000/svg}svg':
        raise ValueError('expected an SVG root')
    safe_svg(root)
    return text, root


def fresh_output(path):
    path = Path(path)
    if path.exists():
        raise ValueError('output already exists; choose a new path to preserve it')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def inspect(path):
    text, root = load_svg(path)
    counts = Counter(n.tag.rsplit('}', 1)[-1] for n in root.iter())
    warnings = []
    if counts['image'] and not counts['text'] and not sum(counts[k] for k in ('rect', 'path', 'circle', 'polygon', 'line')):
        warnings.append('image_only_document')
    return {'canvas': {k: root.get(k) for k in ('width', 'height', 'viewBox')},
            'counts': dict(counts), 'objects': [{'id': n.get('id'), 'type': n.tag.rsplit('}', 1)[-1],
                'text': ''.join(n.itertext()) if n.tag.endswith('}text') else None}
                for n in root.iter() if n.get('id')], 'warnings': warnings,
            'visual_quality_pass': None, 'editability_verified': False,
            'sha256': hashlib.sha256(text.encode()).hexdigest()}


def apply(path, plan_path, source, out):
    text, root = load_svg(path)
    plan = json.loads(Path(plan_path).read_text())
    txs = plan.get('transactions')
    if not isinstance(txs, list):
        raise ValueError('plan requires transactions')
    seen = set()
    for tx in txs:
        if not isinstance(tx.get('id'), str) or not tx['id'] or tx['id'] in seen:
            raise ValueError('transaction IDs must be nonempty and unique')
        deps = tx.get('depends_on')
        if not isinstance(deps, list):
            raise ValueError('depends_on is required; use [] for an independent transaction')
        if not set(deps) <= seen:
            raise ValueError('dependencies must precede their transaction')
        if not isinstance(tx.get('target_ids'), list) or not tx['target_ids']:
            raise ValueError('transaction requires target_ids')
        if not isinstance(tx.get('operations'), list) or not tx['operations']:
            raise ValueError('transaction requires operations')
        for op in tx['operations']:
            if op.get('op') not in OPERATIONS:
                raise ValueError('unsupported portable operation: ' + str(op.get('op')))
        seen.add(tx['id'])
    implementation = {'transactions': [{'id': tx['id'], 'edits': tx['operations']} for tx in txs]}
    validate_implementation(implementation, plan, text)
    operations = [op for tx in txs for op in tx['operations']]
    final, journal = apply_edits(text, operations, source)
    destination = fresh_output(out)
    receipt = destination.with_suffix(destination.suffix + '.receipt.json')
    if receipt.exists():
        raise ValueError('receipt already exists; choose a new output path')
    destination.write_text(final, encoding='utf-8')
    result = {'status': 'execution_complete', 'input_sha256': hashlib.sha256(text.encode()).hexdigest(),
              'output_sha256': hashlib.sha256(final.encode()).hexdigest(),
              'transactions': len(txs), 'operations': len(journal), 'journal': journal,
              'visual_quality_pass': None, 'editability_verified': False}
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def render(path, out):
    load_svg(path)
    destination = fresh_output(out)
    executable = shutil.which('rsvg-convert')
    if executable:
        subprocess.run([executable, '-o', str(destination), str(Path(path).resolve())], check=True)
        backend = 'rsvg-convert'
    else:
        try:
            import cairosvg
        except ImportError as error:
            raise ValueError('rendering requires rsvg-convert or optional CairoSVG') from error
        cairosvg.svg2png(url=str(Path(path).resolve()), write_to=str(destination))
        backend = 'CairoSVG'
    with Image.open(destination) as image:
        image.verify()
    return {'status': 'rendered', 'backend': backend, 'path': str(destination), 'visual_quality_pass': None}


def views(source_path, draft_path, out):
    with Image.open(source_path) as image:
        source = image.convert('RGB')
    with Image.open(draft_path) as image:
        draft = image.convert('RGB')
    if source.size != draft.size:
        raise ValueError('source and draft must have equal canvas dimensions')
    destination = Path(out)
    if destination.exists():
        raise ValueError('view directory already exists; choose a new path')
    destination.mkdir(parents=True)
    width, height = source.size
    boxes = [(0, 0, width // 2, height // 2), (width // 2, 0, width, height // 2),
             (0, height // 2, width // 2, height), (width // 2, height // 2, width, height)]
    if min(width, height) < 2:
        raise ValueError('paired quadrants require both dimensions at least two pixels')
    records = []
    for name, box in zip('ABCD', boxes):
        left, right = source.crop(box), draft.crop(box)
        pair = Image.new('RGB', (left.width + right.width + 12, left.height + 24), 'white')
        pair.paste(left, (0, 24)); pair.paste(right, (left.width + 12, 24))
        draw = ImageDraw.Draw(pair)
        draw.text((4, 4), 'SOURCE ' + name, fill='black')
        draw.text((left.width + 16, 4), 'DRAFT ' + name, fill='black')
        pair.save(destination / (name + '-pair.png'))
        records.append({'region': name, 'whole_pixel_box': box, 'source_left': True})
    result = {'canvas': [width, height], 'regions': records}
    (destination / 'views.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'render', 'apply'):
        command = commands.add_parser(name); command.add_argument('svg')
        if name != 'inspect':
            command.add_argument('--out', required=True)
        if name == 'apply':
            command.add_argument('--plan', required=True); command.add_argument('--source')
    command = commands.add_parser('views')
    command.add_argument('--source', required=True); command.add_argument('--draft', required=True)
    command.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'inspect': result = inspect(args.svg)
        elif args.command == 'render': result = render(args.svg, args.out)
        elif args.command == 'apply': result = apply(args.svg, args.plan, args.source, args.out)
        else: result = views(args.source, args.draft, args.out)
    except (ValueError, KeyError, OSError, ET.ParseError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr); return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
