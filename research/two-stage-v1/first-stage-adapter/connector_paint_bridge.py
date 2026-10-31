"""Prospective F5 adapter. Audit arrays stay local; no model/provider calls."""
from pathlib import Path
import time
import json
import connector_paint_contract as contract

HERE=Path(__file__).resolve().parent
ARCHIVED_PRODUCER_SHA='e1b396a585b59edb753ff6ddf244ec7a7fe7bf29b58e5712849cf55ab2630d90'
ARCHIVED_V3_SHA='b3f506df508d55b1143240c795ea6878b916780f6cbb228d9eba332100efbcde'
PRODUCER_SHA='1ac3e90ff9e56bfc94bfaa5d63aff09d2d9f8e87670ddd608bb8ccc1ad09d956'
CONTRACT_SHA='eef68bf0e022bc627e30d4fcb598ef5f6124c081e1a0b125073df407f2dc2f3d'
PRODUCER_VERSION='neutral-marker-field/4'
METRIC_VERSION='white-composited-rgba-integer-contribution-r2'
# Preflight estimates and a soft callback-boundary time check, NOT process caps.
LIMITS=dict(max_pixels=16_777_216,max_input_bytes=67_108_864,max_peak_bytes=3_221_225_472,max_artifact_bytes=1_073_741_824,soft_seconds=120.0)
SOURCES=('connector_paint_contract.py','connector_paint_producer.py','connector_paint_producer_v3.py','connector_paint_producer_v4.py','connector_paint_bridge.py','docs/connector-paint-observation-contract.md','docs/connector-paint-provenance.md')


def sha(path):return contract.sha256(Path(path).read_bytes())

def load(path):
    try:return contract.parse_raw(Path(path).read_bytes())
    except OSError as exc:raise contract.ContractError('missing/unreadable connector artifact: '+str(path)) from exc

def exclusive(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:stream.write((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())


def approved_versions():
    contract.require(sha(HERE/'connector_paint_contract.py')==CONTRACT_SHA,'approved contract source changed')
    contract.require(sha(HERE/'connector_paint_producer.py')==ARCHIVED_PRODUCER_SHA,'approved producer source changed')
    contract.require(sha(HERE/'connector_paint_producer_v3.py')==ARCHIVED_V3_SHA,'approved V3 producer source changed')
    contract.require(sha(HERE/'connector_paint_producer_v4.py')==PRODUCER_SHA,'approved V4 producer source changed')
    return contract.ApprovedVersions(PRODUCER_SHA,PRODUCER_VERSION,CONTRACT_SHA,METRIC_VERSION)


def prepare_policy(inputs):
    """Intent first, including when approved-source validation later fails."""
    inputs=Path(inputs)
    exclusive(inputs/'connector-paint-preparation-start.json',dict(schema_version='connector-paint-preparation-start-v1',mode=contract.MODE))
    versions=approved_versions()
    policy=dict(schema_version='connector-paint-policy-v2',mode=contract.MODE,approved_producer_version=versions.producer_version,producer_sha256=versions.producer_sha256,contract_sha256=versions.contract_sha256)
    exclusive(inputs/'connector-paint-policy.json',policy)
    return policy


def cohort_extensions(host,base):
    """Inspect only fixed candidate/raw top-level keys; values confer no authority.

    Valid observer-free legacy JSON keeps its permissive duplicate/value parser.
    Malformed UTF-8/JSON, nonobjects or unreadable records cannot establish absence
    and reject explicitly, without normalization or inspecting model-chosen paths.
    """
    active=False
    for relative,keys in ((base+'/candidate.json',('connector_paint',)),(base+'/verifier/raw.json',('connector_paint_ack','connector_visual_concerns','connector_concern_reviews'))):
        path=host.path(relative,exists=False)
        if not path.exists():continue
        path=host.path(relative)
        try:value=json.loads(path.read_bytes())
        except (OSError,ValueError,UnicodeError) as exc:
            raise contract.ContractError('cohort observer inspection cannot establish absent keys: '+relative) from exc
        contract.require(isinstance(value,dict),'cohort observer inspection requires JSON object: '+relative)
        active=any(key in value for key in keys) or active
    return active


def policy(host,state=None):
    import assignment_policy
    if assignment_policy.disabled(host.root):
        for n in (1,2,3):contract.observer_mode(host,n)
        if any(k in (state or {}) for k in ('connector_paint_mode','connector_visual_concerns','connector_concern_receipts')):raise ValueError('disabled connector state carries observer authority')
        return None
    marker=host.path('inputs/connector-paint-preparation-start.json',exists=False)
    contract.require(marker.is_file() and host.path('inputs/connector-paint-policy.json',exists=False).is_file(),'enabled assignment requires connector preparation marker and policy')
    # A named extension key remains activation even if its value is null/empty.
    active=marker.exists() or any(k in (state or {}) for k in ('connector_paint_mode','connector_visual_concerns','connector_concern_receipts'))
    # Policy is cohort-wide: another same-root run cannot leave observer intent
    # behind and then allow a fresh run to infer legacy mode.
    for run in ('run1','run2','run3'):
        prior=host.path('runs/'+run+'/state.json',exists=False)
        if prior.exists():
            value=load(prior)
            active=active or any(k in value for k in ('connector_paint_mode','connector_visual_concerns','connector_concern_receipts'))
        for n in (1,2,3):
            active=cohort_extensions(host,f'runs/{run}/round-{n}') or active
            for name in ('connector-paint-start.json','connector-paint','connector-paint-registration-receipt.json','connector-paint-timing.json','connector-paint-native-timing.jsonl'):
                active=active or host.path(f'runs/{run}/round-{n}/'+name,exists=False).exists()
    policies=[contract.observer_mode(host,n) for n in (1,2,3)]
    value=policies[0]
    if value is None:
        raise ValueError('enabled assignment requires complete connector preparation')
    contract.require(marker.is_file() and load(marker)==dict(schema_version='connector-paint-preparation-start-v1',mode=contract.MODE),'missing/invalid preparation intent')
    versions=approved_versions()
    expected=dict(schema_version='connector-paint-policy-v2',mode=contract.MODE,approved_producer_version=versions.producer_version,producer_sha256=versions.producer_sha256,contract_sha256=versions.contract_sha256)
    contract.require(value==expected,'policy approved source/version mismatch')
    for name in SOURCES:
        contract.require(sha(host.path(name))==sha(HERE/name),'frozen connector source/doc changed: '+name)
    if state is not None:
        contract.require(state.get('connector_paint_mode')==contract.MODE and type(state.get('connector_visual_concerns')) is list and type(state.get('connector_concern_receipts')) is list,'enabled frozen mode/state missing')
    return value


def produce(**kwargs):
    # Lazy import leaves legacy/std-library controller users unchanged.
    import connector_paint_producer_v4 as producer
    kwargs['limits']=producer.Limits(**kwargs['limits'])
    return producer.build(**kwargs)


def build_observer(host,registration,renderer):
    """Exclusive producer directory; intent survives every failed build."""
    reg=registration;versions=approved_versions();policy(host)
    base=host.root/host.round(reg.round_number);out=base/'connector-paint'
    intent=dict(schema_version='connector-paint-intent-v2',mode=contract.MODE,run_id=host.run_id,round_number=reg.round_number,policy_sha256=sha(host.root/'inputs/connector-paint-policy.json'),producer_sha256=versions.producer_sha256,source_sha256=host.frozen_initial['evidence_hashes']['original_png'],before=contract.endpoint(reg.before),candidate=contract.endpoint(reg.candidate),before_locator=reg.before_locator)
    exclusive(base/'connector-paint-start.json',intent)
    before=host.root/reg.before_locator['relative_path'];candidate=base/'candidate'
    paths=dict(before_svg=before/'current.svg',before_png=before/'current.png',candidate_svg=candidate/'current.svg',candidate_png=candidate/'current.png',original_png=host.root/'inputs/initial/original.png')
    expected={key:sha(path) for key,path in paths.items()}
    started=time.monotonic_ns();cpu=time.process_time_ns();native_calls=[]
    def measured(text,png):
        contract.require(len(native_calls)<4,'observer native callback cap exceeded')
        call={'index':len(native_calls)+1,'started_monotonic_ns':time.monotonic_ns(),'process_cpu_started_ns':time.process_time_ns()}
        native_calls.append(call)
        try:return renderer(text,png)
        finally:
            call.update(ended_monotonic_ns=time.monotonic_ns(),process_cpu_ended_ns=time.process_time_ns())
            # Immediately append callback evidence outside exclusive producer files.
            with (base/'connector-paint-native-timing.jsonl').open('a') as stream:stream.write(json.dumps(call)+'\n')
    try:
        report=produce(**paths,output_dir=out,renderer=measured,expected_sha256=expected,limits=dict(LIMITS))
        contract.require(report==load(out/'report.json'),'producer returned/published report differs')
        contract.require(all(sha(path)==expected[key] for key,path in paths.items()),'observer input changed')
        contract.require(report['status'] in ('field_available','field_unavailable'),'unknown producer status')
        scope=host.raster_scope(reg);regions=contract.cell_regions(scope['candidate_png'].width,scope['candidate_png'].height)
        available=report['status']=='field_available'
        cells=[]
        for i,(cell,region) in enumerate(zip(contract.CELLS,regions)):
            count=None
            if available:
                row=report['cells'][i];x,y,w,h=region
                contract.require(row['bounds_xyxy']==[x,y,x+w,y+h],'producer cell geometry mismatch')
                count={k:row[k] for k in ('lost','gained','altered','changed')}
                count.update(before_nonzero=row['before_contributing'],candidate_nonzero=row['candidate_contributing'])
            cells.append(dict(cell=cell,region_xywh=region,counts=count))
        audit=None
        if available:
            audit=dict(path='fields.npz',sha256=sha(out/'fields.npz'))
            contract.require(audit['sha256']==report['audit']['fields_npz_sha256'],'producer audit binding mismatch')
        # Exact schema manifest keeps sizes in a separately hash-bound local receipt.
        inventory={p.name:dict(sha256=sha(p),bytes=p.stat().st_size) for p in sorted(out.iterdir()) if p.is_file()}
        exclusive(out/'artifact-sizes.json',dict(artifacts=inventory,limits=LIMITS,inputs={k:dict(sha256=expected[k],bytes=p.stat().st_size) for k,p in paths.items()}))
        artifacts=[dict(path=p.name,sha256=sha(p)) for p in sorted(out.iterdir()) if p.is_file()]
        manifest=dict(schema_version='connector-paint-manifest-v2',status='complete',intent_sha256=sha(base/'connector-paint-start.json'),artifacts=artifacts)
        exclusive(out/'manifest.json',manifest)
        packet=dict(schema_version='connector-paint-packet-v2',mode=contract.MODE,policy_sha256=intent['policy_sha256'],producer_sha256=versions.producer_sha256,producer_version=versions.producer_version,metric_version=versions.metric_version,manifest_sha256=sha(out/'manifest.json'),source_sha256=intent['source_sha256'],before=intent['before'],candidate=intent['candidate'],before_locator=reg.before_locator,field_status=report['status'],unavailable_reason=None if available else report['reason'],cells=cells,audit=audit,limitations=report['limitations'])
        contract.validate_packet(packet,reg,versions,(scope['candidate_png'].width,scope['candidate_png'].height))
        exclusive(out/'packet.json',packet)
        return dict(mode=contract.MODE,packet_sha256=sha(out/'packet.json'),manifest_sha256=sha(out/'manifest.json'),policy_sha256=intent['policy_sha256'],producer_sha256=versions.producer_sha256)
    finally:
        exclusive(base/'connector-paint-timing.json',dict(started_monotonic_ns=started,ended_monotonic_ns=time.monotonic_ns(),process_cpu_seconds=(time.process_time_ns()-cpu)/1e9,native_callbacks=len(native_calls),native_callback_intervals=native_calls,limits=LIMITS,provider_calls=0,model_http_calls=0,model_tokens=None,time_limit='soft callback-boundary elapsed checks; synchronous native calls are not cancellable'))


def bundle(host,number):
    base=host.root/host.round(number)
    intent=load(base/'connector-paint-start.json')
    reg=contract.Registration(host.run_id,number,contract.canonical(host.resolve_before(intent['before_locator'],number)),contract.canonical(host.snapshot(host.round(number)+'/candidate')),contract.canonical(intent['before_locator']))
    receipt=load(base/'connector-paint-registration-receipt.json')
    directory=host.path(host.round(number)+'/connector-paint',tree=True)
    actual={p.name:dict(sha256=sha(p),bytes=p.stat().st_size) for p in directory.iterdir() if p.is_file()}
    contract.require(receipt.get('observer_artifacts')==actual,'complete observer hash/size inventory mismatch')
    bound=contract.validate_bundle(host,reg,approved_versions(),receipt['candidate_receipt_sha256'])
    dispatch=base/'verifier/dispatch.json'
    if dispatch.exists():contract.require(load(dispatch).get('candidate_receipt_sha256')==bound.candidate_receipt_sha256,'verifier dispatch candidate receipt changed')
    return bound


def briefing(flow,run,number,output):
    host=flow.connector_host(run);bound=flow.connector_bundle(run,number);state=flow.checked_state(run)
    aliases=dict(original_png=str(host.root/'inputs/initial/original.png'),source_png=str(host.root/'inputs/initial/original.png'),before_png=str(host.root/bound.registration.before_locator['relative_path']/'current.png'),candidate_png=str(host.root/host.round(number)/'candidate/current.png'),current_png=str(host.root/host.round(number)/'candidate/current.png'))
    concerns=[]
    for record in state['connector_visual_concerns']:
        resolved=host.resolve_origin(record)
        origin=resolved['origin'];observed=host.root/host.round(resolved['observed_round'])/'candidate/current.png'
        concerns.append(dict(**resolved,historical_raster_paths=dict(original_png=aliases['original_png'],before_png=str(host.root/origin['before_locator']['relative_path']/'current.png'),observed_png=str(observed))))
    target=Path(output)/'connector-concern-context.json'
    exclusive(target,dict(candidate_receipt_sha256=bound.candidate_receipt_sha256,raster_aliases=aliases,concerns=concerns))
    return [host.root/host.round(number)/'connector-paint/packet.json',host.root/'docs/connector-paint-observation-contract.md',target],dict(candidate_receipt_sha256=bound.candidate_receipt_sha256,raster_aliases=aliases)
