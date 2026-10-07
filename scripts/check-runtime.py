"""Offline local execution checks; /health is the only optional service request."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-sam', action='store_true')
    parser.add_argument('--credentials', action='store_true')
    parser.add_argument('--sandbox', action='store_true', help='also require isolated generated Python execution')
    args = parser.parse_args()
    checks = []

    def check(name, action):
        try:
            action()
            checks.append({'check': name, 'ok': True})
        except Exception as exc:
            checks.append({'check': name, 'ok': False, 'error': str(exc)[:1200]})

    def imports():
        import figfox_plus.native.chain
        import numpy, cv2, vtracer
    check('chain and Python dependencies', imports)
    from figfox_plus.assets import rmbg_runtime
    check('local RMBG model and Python paths', rmbg_runtime)
    with tempfile.TemporaryDirectory(prefix='figfox-check-') as tmp:
        work = Path(tmp)/'Unicode path 测试'
        work.mkdir()
        from figfox_plus.native.document import parse, measure
        from figfox_plus.native.tight_tp import measure_tight
        from figfox_plus.sp.content import content_element
        from figfox_plus.image_io import imread
        from figfox_plus.vectorize import vectorize_asset
        from PIL import Image
        root = parse('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60"><rect id="box" x="4" y="4" width="100" height="50" fill="white" stroke="black"/><text id="label" x="10" y="35">中文 α</text></svg>')
        def render():
            result = measure(root, work/'render.png')
            assert 'label' in result['objects'] and (work/'render.png').is_file()
        check('Chromium render and Unicode output', render)
        check('tight geometry measurement', lambda: measure_tight(root, ['label']))
        check('MathJax formula', lambda: content_element('formula', {'tex': r'x_{1}+\sqrt{2}'}))
        crop = work/'图块.png'
        Image.new('RGB', (16, 16), 'red').save(crop)
        check('OpenCV Unicode image path', lambda: imread(crop))
        check('vtracer subprocess', lambda: vectorize_asset({'id': 'probe', 'path': str(crop)}, 'vtracer', work/'vectors'))
        if args.sandbox:
            from figfox_plus.native.review_problem_first_v13.sandbox import run_code
            source = work/'input.svg'
            source.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding='utf-8')
            def sandbox():
                result = run_code('import xml.etree.ElementTree as ET\nET.parse(INPUT_SVG).write(OUTPUT_SVG, encoding="unicode")', source, work/'sandbox')
                if result['status'] != 'executed':
                    raise RuntimeError(result.get('error', 'sandbox failed'))
            check('isolated generated Python', sandbox)
    if args.credentials:
        from figfox_plus.providers import load_key
        for key in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY'):
            check(key+' configured (no API request)', lambda key=key: load_key(key))
    if not args.skip_sam:
        def health():
            with urllib.request.urlopen('http://127.0.0.1:18080/health', timeout=5) as response:
                if response.status != 200:
                    raise ValueError('SAM health check failed')
        check('SAM service /health', health)
    print(json.dumps({'checks': checks, 'api_requests_sent': 0}, ensure_ascii=True, indent=2))
    return 0 if all(row['ok'] for row in checks) else 1


if __name__ == '__main__':
    raise SystemExit(main())
