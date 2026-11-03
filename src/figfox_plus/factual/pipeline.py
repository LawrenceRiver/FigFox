"""Continuous fresh runs and explicitly linked, hash-verified G0 checkpoints."""
import fcntl
import hashlib
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET
from PIL import Image,ImageDraw
from ..state import PLUS_ROOT,write_json
from . import contracts as C,facts as F,views as V


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render(svg,png):
    import cairosvg
    cairosvg.svg2png(url=str(svg),write_to=str(png))


def first(image,folder,sam,send):
    from ..native.pipeline import first as generate
    from ..native.document import serialize
    folder.mkdir(parents=True,exist_ok=True)
    def transport(prompt,images,run_dir,purpose):return send('G0',prompt,{},images,folder/'call')
    root=generate(image,folder,send=transport,capabilities={'version':'capabilities-v1','sam':sam,'code_methods':False})
    return serialize(root)


def run(image,out,*,sam=True,repair=True,checkpoint=None,send=None,g0_builder=None,config=None):
    image=Path(image).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    with (out/'run.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _run(image,out,sam,repair,checkpoint,send,g0_builder or first,config)


def _run(image,out,sam,repair,checkpoint,send,builder,config):
    started=time.monotonic();identity={'source_sha256':sha(image),'sam':sam,'repair':repair,'checkpoint':str(Path(checkpoint).resolve()) if checkpoint else None,'config':config}
    frozen=out/'identity.json'
    if frozen.exists() and json.loads(frozen.read_text())!=identity:raise ValueError('source, capabilities or configuration changed')
    write_json(frozen,identity)
    if (out/'result.json').exists():
        result=json.loads((out/'result.json').read_text())
        if sha(out/'final.svg')!=result['final_sha256'] or sha(out/'final.png')!=result['png_sha256']:raise ValueError('final artifact hash mismatch')
        return result
    if send is None:
        if config is not None:
            from .transport import sender
            send=sender(config,out)
        else:
            def missing(*args):raise ValueError('explicit provider settings required for a fresh live request')
            send=missing
    cp=out/'G0';cp.mkdir(exist_ok=True);svg=cp/'initial.svg'
    manifest=cp/'manifest.json'
    if svg.exists() and manifest.exists():
        saved=json.loads(manifest.read_text())
        C.require(saved['initial_sha256']==sha(svg),'G0 hash mismatch')
        C.require(saved['source_sha256']==sha(image) and saved['sam'] is sam,'G0 source or capability mismatch')
    if not svg.exists():
        if checkpoint:
            source=Path(checkpoint);proof=json.loads((source/'manifest.json').read_text())
            C.require(proof['source_sha256']==sha(image),'checkpoint source mismatch')
            C.require(proof['sam'] is sam,'checkpoint SAM capability mismatch')
            C.require(proof['initial_sha256']==sha(source/'initial.svg'),'checkpoint initial hash mismatch')
            C.require(bool(proof.get('provenance')),'checkpoint provenance required')
            svg.write_bytes((source/'initial.svg').read_bytes());write_json(cp/'origin.json',proof)
        else:svg.write_text(builder(image,cp,sam,send))
    initial=svg.read_text();C.safe_svg(ET.fromstring(initial));render(svg,cp/'initial.png')
    write_json(cp/'manifest.json',{'source_sha256':sha(image),'initial_sha256':sha(svg),'sam':sam,'provenance':{'origin':'checkpoint' if checkpoint else 'fresh','source_checkpoint':identity['checkpoint'],'request_receipts':'call/receipt.json' if not checkpoint else None}})
    images=[image,cp/'initial.png'];source=Image.open(image).convert('RGB');candidate=Image.open(cp/'initial.png').convert('RGB');w,h=source.size
    C.require(candidate.size==source.size,'source and initial canvas differ')
    frames=[]
    for name,box in zip('ABCD',[(0,0,w//2,h//2),(w//2,0,w,h//2),(0,h//2,w//2,h),(w//2,h//2,w,h)]):
        a=source.crop(box);b=candidate.crop(box);a=a.resize((2*a.width,2*a.height));b=b.resize(a.size);pair=Image.new('RGB',(a.width+b.width+12,a.height+24),'white');pair.paste(a,(0,24));pair.paste(b,(a.width+12,24));dr=ImageDraw.Draw(pair);dr.text((4,4),'SOURCE '+name,fill='black');dr.text((a.width+16,4),'INITIAL '+name,fill='black');path=out/(name+'-pair.png');pair.save(path);images.append(path);frames.append({'region':name,'whole_pixel_box':list(box),'display_scale':2,'source_left':True})
    acceptance=None;final=initial
    if repair:
        def stage(name,payload,imgs):
            folder=out/name;folder.mkdir(exist_ok=True);file=folder/'model.json'
            if file.exists():return json.loads(file.read_text())
            prompt=(PLUS_ROOT/'prompts/factual'/ (name.lower()+'.md')).read_text()
            value=send(name,prompt,payload,imgs,folder/'call');write_json(file,value);return value
        raw_g1=stage('G1',{'whole_width':w,'whole_height':h,'crop_map':frames},images)
        g1,bindings=V.bind_requested_unknowns(raw_g1,w,h);F.validate_facts(g1,w,h);write_json(out/'G1-binding.json',bindings)
        detail=[];maps=[]
        for j,r in enumerate(g1.get('detail_requests',[])[:6]):
            a=source.crop(r['source_box']);b=candidate.crop(r['initial_box']);scale=min(4,1024/max(a.width,a.height,b.width,b.height));a=a.resize((max(1,round(a.width*scale)),max(1,round(a.height*scale))));b=b.resize((max(1,round(b.width*scale)),max(1,round(b.height*scale))));pair=Image.new('RGB',(a.width+b.width+12,max(a.height,b.height)+24),'white');pair.paste(a,(0,24));pair.paste(b,(a.width+12,24));path=out/f'detail-{j}.png';pair.save(path);detail.append(path);maps.append({**r,'display_scale':scale,'source_left':True})
        view,aliases,assets=V.project_assets(initial)
        nodes={n.get('id'):[n.tag.rsplit('}',1)[-1]]+([''.join(n.itertext())] if n.tag.rsplit('}',1)[-1] in ['text','tspan'] else []) for n in ET.fromstring(initial).iter() if n.get('id')}
        operations=json.loads((Path(__file__).parent/'operations.json').read_text())['description']
        payload={'initial_svg':view,'object_index':nodes,'G1_report':g1,'whole_width':w,'whole_height':h,'supported_operations':operations,'requested_detail_map':maps,'immutable_inline_asset_aliases':assets}
        raw_g2=stage('G2',payload,images+detail);g2,nav=V.bind_global_navigation(raw_g2,w,h);g2=V.restore_plan(g2,aliases)
        F.validate_fact_checks(g2,g1);effective=F.effective_findings(g1,g2);C.validate_findings(effective,w,h);C.validate_plan(g2,effective,initial);implementation=F.implementation(g2);C.validate_implementation(implementation,g2,initial)
        edits=[e for tx in implementation['transactions'] for e in tx['edits']];final,journal=C.apply_edits(initial,edits,image)
        acceptance={'accepted':True,'initial_sha256':sha(svg),'final_sha256':hashlib.sha256(final.encode()).hexdigest(),'planned_operations':len(edits),'executed_operations':len(journal),'unresolved':g2['unresolved']}
        write_json(out/'implementation.json',implementation);write_json(out/'native-acceptance.json',acceptance);write_json(out/'G2-navigation.json',nav)
    (out/'final.svg').write_text(final);render(out/'final.svg',out/'final.png')
    result={'status':'execution_complete','visual_quality_pass':None,'scoring_status':'not_scored','source_sha256':sha(image),'initial_sha256':sha(svg),'final_sha256':sha(out/'final.svg'),'png_sha256':sha(out/'final.png'),'sam':sam,'repair':repair,'native_acceptance':acceptance,'checkpoint_reused':bool(checkpoint),'elapsed_seconds_this_process':time.monotonic()-started,'clock_scope':'checkpoint continuation' if checkpoint else 'continuous fresh run including G0 preparation','same_process_completion':True}
    write_json(out/'result.json',result);return result


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description='Reference to native SVG through G0, factual detection, independent planning and local execution')
    p.add_argument('--image',required=True);p.add_argument('--out',required=True);p.add_argument('--config',required=True);p.add_argument('--checkpoint');p.add_argument('--no-sam',action='store_true');p.add_argument('--no-repair',action='store_true')
    a=p.parse_args(argv);print(json.dumps(run(a.image,a.out,sam=not a.no_sam,repair=not a.no_repair,checkpoint=a.checkpoint,config=json.loads(Path(a.config).read_text())),indent=2))

if __name__=='__main__':main()
