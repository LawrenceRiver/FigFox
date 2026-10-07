"""Shared datasets and comparable experiment folders; model calls only in run-figfox."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT/'benchmark'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identifier(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', value):
        raise ValueError('IDs must contain only lowercase letters, digits, underscores or hyphens')
    return value


def load_dataset(path):
    path = Path(path).resolve()
    data = read(path)
    identifier(data['id'])
    seen = set()
    if not data['samples']:
        raise ValueError('dataset has no samples')
    for sample in data['samples']:
        identifier(sample['id'])
        if sample['id'] in seen:
            raise ValueError('duplicate sample ID: '+sample['id'])
        seen.add(sample['id'])
        image = (path.parent/sample['image']).resolve()
        if not image.is_relative_to(path.parent) or sha(image) != sample['sha256']:
            raise ValueError('image path or hash mismatch: '+sample['id'])
    return data


def add_dataset(dataset_id, images, source):
    identifier(dataset_id)
    folder = WORKSPACE/'datasets'/dataset_id
    images = [Path(p).resolve() for p in images]
    if not images or any(not p.is_file() or p.suffix.lower() not in ('.png','.jpg','.jpeg','.webp') for p in images):
        raise ValueError('supply existing PNG, JPG or WebP images')
    if len(images) != len(set(images)):
        raise ValueError('duplicate input paths')
    folder.mkdir(parents=True, exist_ok=False)
    (folder/'images').mkdir()
    (folder/'annotations').mkdir()
    (folder/'source').mkdir()
    samples = []
    for index, original in enumerate(images, 1):
        sample_id = f'sample-{index:04d}'
        relative = 'images/'+sample_id+'-'+original.name
        shutil.copyfile(original, folder/relative)
        samples.append({'id':sample_id, 'image':relative, 'original_filename':original.name,
                        'sha256':sha(original), 'split':'unassigned', 'reference_svg':None})
    write(folder/'dataset.json', {'schema_version':1, 'id':dataset_id, 'source':source,
                                 'created_at':datetime.now(timezone.utc).isoformat(), 'samples':samples})
    (folder/'README.md').write_text(
        '# '+dataset_id+'\n\n来源：'+source+'\n\n'
        'images/ 保存原图；annotations/ 保存参考 SVG 或标注；source/ 保存上游说明、许可和原始清单。\n'
        'dataset.json 是样本清单。样本编号一经用于实验，不重新编号；修改图片或样本集合时创建新版本数据集。\n'
        'split 未指定，不能自动视为独立测试集。原图不会自动缩放或格式转换。\n', encoding='utf-8')
    return folder


def collect(run):
    """Export the FigFox evidence batch into the shared, sample-ID-based layout."""
    run = Path(run).resolve()
    meta = read(run/'run.json')
    dataset = read(run/'dataset.json')
    samples = {s['id']:s for s in dataset['samples']}
    raw = run/meta['raw_dir']
    rows = []
    cards = []
    for case_id, sample_id in meta['case_map'].items():
        identifier(case_id); identifier(sample_id)
        cases = list(raw.glob(case_id+'-*/summary.json'))
        if len(cases) != 1:
            raise ValueError('expected one completed or failed case summary for '+case_id)
        case = cases[0].parent
        summary = read(cases[0])
        sample = samples[sample_id]
        if summary['source_sha256'] != sample['sha256']:
            raise ValueError('case input differs from registered dataset: '+sample_id)
        target = run/'samples'/sample_id
        target.mkdir(parents=True, exist_ok=True)
        artifacts = {}
        for name in ('baseline.svg','baseline.png','final.svg','final.png','raw-model.svg','costs.json'):
            if (case/name).is_file():
                shutil.copyfile(case/name, target/name)
                artifacts[name] = 'samples/'+sample_id+'/'+name
        row = {'sample_id':sample_id, 'original_filename':sample['original_filename'],
               'status':summary['status'], 'exit_code':summary.get('exit_code'),
               'elapsed_seconds':summary.get('elapsed_seconds'), 'model_requests':summary['model_requests'],
               'estimated_usd':summary['estimated_usd'] if summary['cost_complete'] else None,
               'known_estimated_usd':summary['estimated_usd'], 'cost_complete':summary['cost_complete'],
               'output_stage':summary['output_stage'], 'visual_passed':summary['visual_passed']}
        row.update({key:summary.get(key) for key in ('execution_status','review_status','artifact_status','review_complete','additional_estimated_usd','recovery_elapsed_seconds','elapsed_time_complete','input_tokens','cached_input_tokens','output_tokens','reasoning_tokens','total_tokens','token_usage_complete','started_at','finished_at','api_cost_mode','api_cost_target_usd','cost_target_status','api_budget_usd')})
        write(target/'sample.json', {**row, 'input_sha256':sample['sha256'], 'artifacts':artifacts,
                                    'evidence_dir':str(case.relative_to(run)),
                                    'changed_programs':summary.get('changed_programs'),
                                    'error':summary.get('error')})
        rows.append(row)
        links = ' · '.join(f'<a href="{html.escape(path, quote=True)}">{html.escape(name)}</a>'
                           for name,path in artifacts.items() if name != 'costs.json')
        preview = '<img src="'+artifacts['final.png']+'">' if 'final.png' in artifacts else ''
        target_note = (' | 费用目标 $'+str(row['api_cost_target_usd'])+': '+
            {'exceeded':'已超过目标，保留生成额度','within_target':'在目标内','unknown':'用量尚不完整'}.get(row['cost_target_status'],'用量尚不完整')
            if row['api_cost_target_usd'] is not None else '')
        cards.append('<section><h2>'+html.escape(sample_id+' — '+sample['original_filename'])+'</h2><p>'+
                     html.escape(str(row['status'])+' | '+('$'+str(row['estimated_usd']) if row['cost_complete'] else '费用不完整')+target_note)+'</p>'+links+preview+'</section>')
    cost_complete = all(r['cost_complete'] for r in rows)
    known_cost = round(sum(r['known_estimated_usd'] for r in rows),6)
    write(run/'summary.json', {'dataset_id':dataset['id'], 'method_id':meta['method_id'], 'samples':rows,
                              'estimated_usd':known_cost if cost_complete else None,
                              'known_estimated_usd':known_cost, 'cost_complete':cost_complete})
    with (run/'summary.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    (run/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Experiment results</title>'
        '<style>body{font:16px system-ui;max-width:1400px;margin:32px auto}img{display:block;max-width:100%;margin:16px 0}section{margin:40px 0}</style>'
        '<h1>'+html.escape(dataset['id']+' / '+meta['method_id'])+'</h1>'
        '<p>运行完成不等于视觉验收；费用为 token 估算。完整证据在 raw/。</p>'+''.join(cards), encoding='utf-8')
    if any(r.get('execution_status')=='failed' or (r['exit_code']!=0 and r.get('execution_status')!='blocked') for r in rows):
        meta['status']='has_failures'
    elif any(r.get('execution_status')=='blocked' for r in rows):
        meta['status']='blocked'
    elif any(r.get('execution_status')=='completed_with_issues' for r in rows):
        meta['status']='completed_with_issues'
    else:
        meta['status']='completed'
    write(run/'run.json', meta)
    return rows


def run_figfox(dataset_id, run_id, selected_samples=None):
    identifier(dataset_id); identifier(run_id)
    manifest = WORKSPACE/'datasets'/dataset_id/'dataset.json'
    dataset = load_dataset(manifest)
    samples=dataset['samples']
    if selected_samples:
        if set(selected_samples)-{s['id'] for s in samples}:raise ValueError('Unknown sample IDs')
        samples=[s for s in samples if s['id'] in selected_samples]
    images = [manifest.parent/s['image'] for s in samples]
    if any(p.suffix.lower() != '.png' for p in images):
        raise ValueError('FigFox currently accepts PNG only; create a documented converted dataset version')
    run = WORKSPACE/'runs'/dataset_id/'figfox'/run_id
    if run.exists():raise ValueError('run already exists; use a new run ID')
    spec = importlib.util.spec_from_file_location('batch_experiment', ROOT/'scripts/batch-experiment.py')
    batch = importlib.util.module_from_spec(spec); spec.loader.exec_module(batch)
    batch.load_environment()
    run.mkdir(parents=True)
    shutil.copyfile(manifest,run/'dataset.json')
    shutil.copyfile(WORKSPACE/'methods/figfox/method.json',run/'method.json')
    write(run/'run.json', {'schema_version':1, 'dataset_id':dataset_id, 'method_id':'figfox', 'run_id':run_id,
                          'dataset_manifest_sha256':sha(manifest), 'dataset_dir':str(manifest.parent),
                          'raw_dir':'raw', 'status':'running', 'started_at':datetime.now(timezone.utc).isoformat(),
                          'case_map':{f'case-{i:03d}':s['id'] for i,s in enumerate(samples,1)}})
    command = [sys.executable,'-u',str(ROOT/'scripts/batch-experiment.py'),*[str(p) for p in images],
               '--out',str(run/'raw')]
    try:
        result = subprocess.run(command,cwd=ROOT)
        if (run/'raw/summary.json').exists():
            collect(run)
        else:
            meta = read(run/'run.json')
            meta.update(status='failed_before_results',exit_code=result.returncode)
            write(run/'run.json',meta)
        return result.returncode
    finally:
        print(str(run),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    add = commands.add_parser('add-dataset',help='copy original images and register stable sample IDs; no API')
    add.add_argument('--id',required=True); add.add_argument('--source',required=True)
    add.add_argument('images',nargs='*',type=Path); add.add_argument('--input-dir',type=Path)
    run = commands.add_parser('run-figfox',help='run FigFox on a registered dataset; uses model APIs')
    run.add_argument('--dataset',required=True)
    run.add_argument('--samples',nargs='+',help='fixed sample IDs; default all samples')
    run.add_argument('--run-id',default=datetime.now().strftime('%Y%m%d-%H%M%S'))
    export = commands.add_parser('collect',help='refresh FigFox exports and summaries; no API')
    export.add_argument('run',type=Path)
    args = parser.parse_args()
    if args.command == 'add-dataset':
        images = args.images
        if args.input_dir:
            images += sorted(p for p in args.input_dir.iterdir() if p.is_file() and p.suffix.lower() in ('.png','.jpg','.jpeg','.webp'))
        print(add_dataset(args.id,images,args.source)); return 0
    if args.command == 'collect':collect(args.run); return 0
    return run_figfox(args.dataset,args.run_id,args.samples)


if __name__ == '__main__':
    raise SystemExit(main())
