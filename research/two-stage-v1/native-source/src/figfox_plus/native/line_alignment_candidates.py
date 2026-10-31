"""Supplement current-only line facts with local mirrored-endpoint hypotheses.

Never modifies facts, prunes all-pair evidence, or judges a defect. The input's
parallel_groups already bind presentation and directed parallel geometry. We add
shared endpoint baselines, proximity, and approximate transverse symmetry gates.
Axes come from current group extents, not labels, reference pixels or expectations.
"""
from copy import deepcopy
import hashlib
import json
import math
from statistics import median


def _finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _point(value):
    return isinstance(value,(list,tuple)) and len(value)==2 and all(_finite(v) for v in value)


def _dot(a,b):return a[0]*b[0]+a[1]*b[1]


def summarize_line_alignment(facts, *, tolerance=None, local_gap_factor=2.0, max_span_factor=6.0, symmetry_span_fraction=0.10):
    """Return auditable hypotheses without changing or replacing original facts.

    Four or more members are required: two arbitrary lines always admit a midpoint
    axis. Locality uses median shaft length, not figure-specific coordinates. The
    existing measured distance tolerance is used for baselines and endpoint/length
    differences, defaulting to 0.5 scene units. Transverse pair-sum residuals may
    separately reach max(tolerance, symmetry_span_fraction * transverse span).
    Default fraction 0.10 is a generic hypothesis gate, not measurement accuracy
    or an acceptance tolerance. Zero restores the measurement-only symmetry gate.
    """
    if tolerance is None:tolerance=facts.get('thresholds',{}).get('distance',0.5)
    for value in (tolerance,local_gap_factor,max_span_factor):
        if not _finite(value) or value<=0:raise ValueError('thresholds must be finite positive numbers')
    if not _finite(symmetry_span_fraction) or not 0<=symmetry_span_fraction<=0.5:raise ValueError('symmetry_span_fraction must lie in [0, 0.5]')
    result={'candidates':[], 'coverage':{'parallel_groups_examined':0,'eligible_members':0},
        'parameters':{'tolerance':tolerance,'local_gap_factor':local_gap_factor,'max_span_factor':max_span_factor,'minimum_members':4,'symmetry_span_fraction':symmetry_span_fraction},
        'instruction':'Hypotheses only. Compare each candidate with the original image; intentional unequal lengths and asymmetry are valid. No original coordinates were inferred. Existing all-pair evidence remains authoritative measurement input, not an error verdict.',
        'limitations':['Requires at least four local, equally presented directed parallel shafts with a shared endpoint baseline and approximately mirrored transverse arrangement.',
            'Groups without a shared baseline, tiny groups, differing styles or opposite path order can be missed.',
            'Locality and transverse symmetry do not prove semantic relatedness; unrelated grid lines can qualify.',
            'The candidate axis belongs to the current group; it does not establish a container axis or intended symmetry.',
            'Endpoints are measured centerline endpoints, not marker tips. Existing sampling, clipping, masking and visibility limitations remain.']}
    seen=set()
    for group_index,group in enumerate(facts.get('parallel_groups',[])):
        result['coverage']['parallel_groups_examined']+=1
        direction=group.get('direction')
        if not _point(direction) or math.hypot(*direction)==0:continue
        norm=math.hypot(*direction);axis=[v/norm for v in direction];perp=[-axis[1],axis[0]]
        members=[];ids=set()
        for source in group.get('members',[]):
            if not isinstance(source,dict):continue
            oid=source.get('object_id');start=source.get('world_start');end=source.get('world_end');length=source.get('world_arc_length')
            if not isinstance(oid,str) or not oid or oid in ids or not _point(start) or not _point(end) or not _finite(length) or length<=0:continue
            ids.add(oid)
            members.append({'object_id':oid,'world_start':deepcopy(start),'world_end':deepcopy(end),'world_arc_length':length,
                'start_projection':_dot(start,axis),'end_projection':_dot(end,axis),
                'perpendicular_position':_dot([(start[j]+end[j])/2 for j in (0,1)],perp)})
        result['coverage']['eligible_members']+=len(members)
        for endpoint in ('start','end'):
            field=endpoint+'_projection';baselines=[]
            # Complete-link scalar clustering: no accumulated tolerance chaining.
            for member in sorted(members,key=lambda m:m[field]):
                if not baselines or member[field]-baselines[-1][0][field]>tolerance:baselines.append([])
                baselines[-1].append(member)
            for baseline in baselines:
                scale=median(m['world_arc_length'] for m in baseline)
                ordered=sorted(baseline,key=lambda m:m['perpendicular_position']);clusters=[]
                for member in ordered:
                    if (not clusters or member['perpendicular_position']-clusters[-1][-1]['perpendicular_position']>local_gap_factor*scale
                            or member['perpendicular_position']-clusters[-1][0]['perpendicular_position']>max_span_factor*scale):clusters.append([])
                    clusters[-1].append(member)
                for cluster in clusters:
                    if len(cluster)<4:continue
                    positions=[m['perpendicular_position'] for m in cluster]
                    if any(b-a<=tolerance for a,b in zip(positions,positions[1:])):continue
                    center=(positions[0]+positions[-1])/2
                    transverse_span=positions[-1]-positions[0]
                    symmetry_limit=max(tolerance,symmetry_span_fraction*transverse_span)
                    if any(abs(positions[i]+positions[-1-i]-2*center)>symmetry_limit for i in range((len(cluster)+1)//2)):continue
                    pairs=[]
                    for i in range(len(cluster)//2):
                        a,b=cluster[i],cluster[-1-i]
                        pairs.append({'member_ids':[a['object_id'],b['object_id']],
                            'transverse_symmetry_residual':abs(a['perpendicular_position']+b['perpendicular_position']-2*center),
                            'start_projection_delta':b['start_projection']-a['start_projection'],
                            'end_projection_delta':b['end_projection']-a['end_projection'],
                            'length_delta':b['world_arc_length']-a['world_arc_length']})
                    if not any(max(abs(p[k]) for k in ('start_projection_delta','end_projection_delta','length_delta'))>tolerance for p in pairs):continue
                    identity=tuple(m['object_id'] for m in cluster)
                    if identity in seen:continue
                    seen.add(identity)
                    baseline_value=sum(m[field] for m in cluster)/len(cluster)
                    result['candidates'].append({'candidate_id':'line-alignment-'+hashlib.sha256(json.dumps([group_index,identity,endpoint]).encode()).hexdigest()[:16],
                        'source_parallel_group_index':group_index,'member_ids':list(identity),'members':deepcopy(cluster),'mirror_pairs':pairs,
                        'baseline':{'endpoint':endpoint,'projection':baseline_value,'span':max(m[field] for m in cluster)-min(m[field] for m in cluster)},
                        'transverse_symmetry':{'span':transverse_span,'allowed_residual':symmetry_limit,'span_fraction':symmetry_span_fraction,'max_pair_sum_residual':max(abs(positions[i]+positions[-1-i]-2*center) for i in range((len(cluster)+1)//2)),'residual_definition':'absolute(a_perpendicular+b_perpendicular-2*axis_perpendicular); hypothesis gate only'},
                        'axis':{'direction':axis[:],'perpendicular_position':center,'point':[axis[j]*baseline_value+perp[j]*center for j in (0,1)],'basis':'midpoint of current local group transverse extents'},
                        'hypothesis_reason':'Same presentation and directed parallel group; local shared baseline; transverse positions approximately mirror about a current group axis within the separately reported scale-relative hypothesis tolerance, but mirrored endpoint projections or shaft lengths differ.',
                        'requires_original_visual_confirmation':True,'is_error_verdict':False})
    return result
