"""Offline current-only near-coincident shaft hypotheses, including curved paths.

Browser geometry is sampled, not certified identical. Neither endpoints nor
centerline overlap establishes arrow intent, marker semantics or a visual defect.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from ..runtime import browser_environment, node_command
from .current_line_facts import build_line_facts


def _distance(a,b):return math.hypot(a[0]-b[0],a[1]-b[1])


def _resample(points,count=65):
    cumulative=[0.0]
    for a,b in zip(points,points[1:]):cumulative.append(cumulative[-1]+_distance(a,b))
    if cumulative[-1]<=0:raise ValueError('zero sampled length')
    output=[];j=1
    for i in range(count):
        target=cumulative[-1]*i/(count-1)
        while j<len(points)-1 and cumulative[j]<target:j+=1
        span=cumulative[j]-cumulative[j-1];fraction=(target-cumulative[j-1])/span if span else 0
        output.append([points[j-1][k]+fraction*(points[j][k]-points[j-1][k]) for k in (0,1)])
    return output,cumulative[-1]


def build_coincident_path_candidates(svg_path, facts=None, *, distance_fraction=0.02, distance_floor=0.5, length_ratio_limit=1.15):
    """Supplement facts without modifying them; optional facts avoid remeasurement.

    Supplied facts must correspond to the same immutable current SVG snapshot.

    Distance gates use max(2% of shorter shaft arc length, 0.5 scene units,
    half sum of current-world stroke-width upper bounds), plus arc-length
    ratio <=1.15, matching stroke color, and stroke-width ratio <=1.5. These are
    generic hypothesis gates, never visual acceptance thresholds. All samples
    are world-space current coordinates, never transferable to original crops.
    """
    for value in (distance_fraction,distance_floor,length_ratio_limit):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('invalid threshold')
    if length_ratio_limit<1:raise ValueError('length ratio limit must be >=1')
    try:root=ET.fromstring(Path(svg_path).read_text())
    except ET.ParseError as exc:raise ValueError('Malformed SVG XML') from exc
    svg_namespace='http://www.w3.org/2000/svg'
    if root.tag not in ('svg','{'+svg_namespace+'}svg'):raise ValueError('Input must be an SVG document in the SVG namespace')
    if root.tag=='svg':
        for node in root.iter():
            if isinstance(node.tag,str) and not node.tag.startswith('{'):node.tag='{'+svg_namespace+'}'+node.tag
    if facts is None:facts=build_line_facts(svg_path)
    eligible={o['object_id']:o for o in facts['objects'] if o.get('measurement_status')=='measured' and o.get('tag') in ('line','polyline','path') and o.get('style',{}).get('display')!='none' and o.get('style',{}).get('visibility')!='hidden' and o.get('style',{}).get('stroke') not in (None,'none')}
    for node in root.iter():
        for child in list(node):
            if child.tag.rsplit('}',1)[-1] in {'script','foreignObject','animate','animateMotion','animateTransform','set'}:node.remove(child)
        for attr in list(node.attrib):
            if attr.lower().startswith('on'):del node.attrib[attr]
    env=browser_environment()
    runtime=Path(__file__).resolve().parents[3]/'runtime/coincident-path-samples.cjs'
    run=subprocess.run([node_command(),str(runtime)],input=json.dumps({'svg':ET.tostring(root,encoding='unicode'),'ids':list(eligible),'count':257}),text=True,capture_output=True,env=env,timeout=120)
    if run.returncode:raise ValueError('offline shaft sampling failed: '+run.stderr[:1000])
    samples=json.loads(run.stdout);resampled={};envelopes={r['object_id']:r['stroke_envelope'] for r in samples['records']}
    for record in samples['records']:
        try:resampled[record['object_id']]=_resample(record['points'])
        except ValueError:continue
    report={'domain':'current_svg_only','candidates':[],'sampling':{'points_per_path':257,'comparison_points':65,'method':'browser getPointAtLength then world-space polyline arc-length resampling'},
        'parameters':{'distance_fraction':distance_fraction,'distance_floor':distance_floor,'length_ratio_limit':length_ratio_limit,'stroke_width_ratio_limit':1.5},
        'coverage':{'eligible_objects':len(eligible),'sampled_objects':len(resampled),'pairs_examined':0},'unsupported':samples['unsupported'],
        'instruction':'These are distinct current shaft objects with nearby sampled centerlines, not proven duplicate arrows. Compare original SAM evidence when supplied and original PNG/Crops to confirm intended shaft count, direction and connections. Intentional parallel arrows may qualify and must be retained. A single double-headed shaft is never paired with itself.',
        'limitations':['Finite sampling can miss small loops and local deviations; this is not a continuous-curve distance certificate.', 'Stroke envelope uses the largest affine singular value: exact under uniform scaling, conservative under nonuniform scaling/shear; it can suggest proximity without actual painted overlap. Non-scaling strokes and unresolved widths are explicitly unsupported.', 'Markers, joins, caps, occlusion, clipping, opacity and dash paint are not resolved by centerline proximity.', 'Different stroke colors or widths, compound paths, closed paths, raster arrows and use instances can be missed.', 'Matching style and shape do not prove semantic duplication. No error verdict or repair instruction is inferred.']}
    ids=list(resampled)
    for i,aid in enumerate(ids):
        for bid in ids[i+1:]:
            report['coverage']['pairs_examined']+=1
            a=eligible[aid];b=eligible[bid];sa=a['style'];sb=b['style']
            if sa.get('stroke')!=sb.get('stroke'):continue
            wa=envelopes[aid]['world_width_upper_bound'];wb=envelopes[bid]['world_width_upper_bound']
            if max(wa,wb)/min(wa,wb)>1.5:continue
            ap,al=resampled[aid];bp,bl=resampled[bid]
            if max(al,bl)/min(al,bl)>length_ratio_limit:continue
            components={'absolute_floor':distance_floor,'relative_length':distance_fraction*min(al,bl),'stroke_envelope':(wa+wb)/2}
            limit=max(components.values())
            direct=max(_distance(ap[0],bp[0]),_distance(ap[-1],bp[-1]));reverse=max(_distance(ap[0],bp[-1]),_distance(ap[-1],bp[0]))
            if min(direct,reverse)>limit:continue
            reversed_order=reverse<direct;ordered=list(reversed(bp)) if reversed_order else bp
            distances=[_distance(p,q) for p,q in zip(ap,ordered)]
            if max(distances)>limit:continue
            report['candidates'].append({'candidate_id':'coincident-'+hashlib.sha256(json.dumps([aid,bid]).encode()).hexdigest()[:16],
                'member_ids':[aid,bid],'orientation':'reversed' if reversed_order else 'direct',
                'measured_endpoints':{oid:{'start':eligible[oid]['world_start'],'end':eligible[oid]['world_end'],'world_arc_length':eligible[oid]['world_arc_length'],'markers':deepcopy(eligible[oid].get('markers',{}))} for oid in (aid,bid)},
                'tolerance_components':components,'stroke_envelopes':[deepcopy(envelopes[oid]) for oid in (aid,bid)],
                'endpoint_distances':{'direct_max':direct,'reversed_max':reverse},'sampled_arc_lengths':[al,bl],
                'shape_distance':{'max':max(distances),'rms':math.sqrt(sum(d*d for d in distances)/len(distances)),'allowed':limit,'comparison':'aligned normalized world arc-length samples'},
                'hypothesis_reason':'Distinct nearby endpoint pairs, comparable style and arc length, and close sampled shape throughout the shaft.',
                'requires_original_visual_confirmation':True,'is_error_verdict':False})
    return report
