"""Explicit commands; importing or asking for help never sends requests."""
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog='figfox-plus', description='Plus semantic SVG pipeline')
    commands = parser.add_subparsers(dest='command')
    offline = commands.add_parser('offline')
    offline.add_argument('--out', help='parent directory for a new evidence run')
    commands.add_parser('manual-eval')
    run=commands.add_parser('run');run.add_argument('--image',required=True);run.add_argument('--rounds',type=int,default=1,choices=(0,1))
    chain=commands.add_parser('chain',help='original image through GPT-5.5, crops, two DeepSeek calls, and one receipt follow-up when needed')
    chain.add_argument('--image',required=True)
    chain.add_argument('--out',required=True)
    chain.add_argument('--id',required=True,help='short image id, for example unet')
    chain.add_argument('--rerun-authorization',required=True,help='one-time string allowing GPT-5.5 to run again on an original it has already seen')
    resume=commands.add_parser('resume');resume.add_argument('--run',required=True);resume.add_argument('--rounds',type=int,default=1,choices=(1,))
    prep=commands.add_parser('repair-prepare',help='prepare all images and 12 inputs locally; no API request')
    prep.add_argument('--sources',required=True);prep.add_argument('--run',required=True)
    once=commands.add_parser('repair-once',help='one DeepSeek request per prepared task, then local execution')
    once.add_argument('--run',required=True)
    local=commands.add_parser('repair-execute',help='execute a saved response locally; never sends requests')
    local.add_argument('--run',required=True)
    feedback=commands.add_parser('repair-feedback',help='one explicitly requested feedback call; total task ceiling two')
    feedback.add_argument('--run',required=True)
    replay=commands.add_parser('repair-replay',help='replay saved output in a new local directory; no model calls')
    replay.add_argument('--run',required=True);replay.add_argument('--out',required=True)
    review_prep=commands.add_parser('review-prepare',help='consume upstream crop handoff and prepare twelve inputs; no API')
    review_prep.add_argument('--bundle',required=True);review_prep.add_argument('--run',required=True)
    review_run=commands.add_parser('review-run',help='execute complete review and real tool feedback; at most two model requests')
    review_run.add_argument('--run',required=True);review_run.add_argument('--request-limit',type=int,choices=(1,2),default=1)
    report=commands.add_parser('report');report.add_argument('--run',required=True)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command in ('review-prepare','review-run'):
        import json
        from pathlib import Path
        from .native.review_pipeline.orchestrator import prepare,run
        if args.command=='review-prepare':prepare(json.loads(Path(args.bundle).read_text()),args.run)
        else:run(args.run,request_limit=args.request_limit)
        print(str(Path(args.run).resolve()));return 0
    if args.command in ('repair-prepare','repair-once','repair-execute','repair-feedback','repair-replay'):
        import json
        from pathlib import Path
        from .native.single_call.runner import prepare,run_prepared,execute_saved
        if args.command=='repair-prepare':
            prepare(json.loads(Path(args.sources).read_text()),args.run)
        elif args.command=='repair-once':run_prepared(args.run)
        elif args.command=='repair-feedback':
            from .native.single_call.feedback import run_feedback
            run_feedback(args.run)
        elif args.command=='repair-replay':
            from .native.single_call.runner import replay_saved
            replay_saved(args.run,args.out)
        else:execute_saved(args.run)
        print(str(Path(args.run).resolve()));return 0
    if args.command == 'offline':
        from .offline import run_gallery
        print(run_gallery(args.out))
        return 0
    if args.command=='run':
        from .native.pipeline import run_image
        print(run_image(args.image,args.rounds));return 0
    if args.command=='chain':
        from .native.chain import run_chain
        run_chain(args.image,args.out,image_id=args.id,rerun_authorization=args.rerun_authorization)
        return 0
    if args.command in ('resume','report'):
        import json
        from pathlib import Path
        folder=Path(args.run);state=json.loads((folder/'run.json').read_text())
        if args.command=='report':print(json.dumps(state,ensure_ascii=False,indent=2));return 0
        if str(state.get('execution_source','')).endswith('native') or state.get('execution_source')=='native-gpt55':
            from .native.pipeline import resume as native_resume
            print(native_resume(folder,args.rounds));return 0
        from .pipeline import repair
        from .state import write_json
        stage=Path(state['latest_stage']);scene=json.loads((stage/'scene.json').read_text());number=int(stage.name.split('-')[-1])+1
        try:
            _,latest,status=repair(state['original'],scene,folder,args.rounds,start_round=number)
        except Exception as error:
            state=json.loads((folder/'run.json').read_text())
            state.update(status='failed',error_type=type(error).__name__,error=str(error)[:1000],visual_passed=False)
            write_json(folder/'run.json',state)
            raise
        state.pop('error',None);state.pop('error_type',None)
        feedback=folder/'repair-feedback.json'
        if status=='execution_failed' and feedback.exists():
            failure=json.loads(feedback.read_text());state.update(error=failure['error'],error_type=failure['error_type'])
        state.update(latest_stage=str(Path(latest).resolve()),status=status,visual_passed=False);write_json(folder/'run.json',state);print(folder);return 0
    print(f'{args.command}: not implemented; no model request sent', file=sys.stderr)
    return 2
