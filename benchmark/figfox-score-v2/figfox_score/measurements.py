"""Opt-in measurements on caller-attested correspondences; never image recognition."""
import hashlib,math,warnings
from pathlib import Path
from decimal import Decimal,localcontext

def load_image_module():
 from PIL import Image
 return Image

def attested(p):return p['source']=='human' and p['verified'] and bool(p['refs'])

def validate_image_case(a):
 for key in ['reference_region','candidate_region']:
  r=a[key]
  if len(r)!=4 or any(type(v) is not int for v in r) or min(r[:2])<0 or min(r[2:])<=0:raise ValueError('invalid integer image ROI: '+key)
 t=a['transform'];s=t['scale'];trans=t['translation']
 if type(s) not in (int,float) or not math.isfinite(s) or s<=0 or len(trans)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in trans):raise ValueError('invalid image transform')
 if s!=1 and not t['allow_uniform_scale']:raise ValueError('uniform scale not authorized')
 if any(v!=0 for v in trans) and not t['allow_translation']:raise ValueError('translation not authorized')
 expected=[a['reference_region'][0]*s+trans[0],a['reference_region'][1]*s+trans[1],a['reference_region'][2]*s,a['reference_region'][3]*s]
 if any(not math.isclose(v,w,rel_tol=0,abs_tol=1e-9) for v,w in zip(expected,a['candidate_region'])):raise ValueError('ROIs disagree with declared uniform transform; no nonuniform warp/search permitted')
 if a['reference_region'][2]*a['reference_region'][3]>4_000_000:raise ValueError('ROI exceeds 4M pixel measurement limit')

def measure_local_image(a,base,enabled=False):
 if not enabled:return dict(state='disabled',reason='opt_in_disabled',computed=False)
 validate_image_case(a)
 if not attested(a['identity_evidence']):return dict(state='unknown',reason='asset_identity_not_verified',computed=False)
 try:Image=load_image_module()
 except ImportError:return dict(state='unknown',reason='optional_dependency_Pillow_missing',computed=False)
 crops=[];hashes=[]
 for key,region in [('reference_file','reference_region'),('candidate_file','candidate_region')]:
  p=Path(base)/a[key]
  try:
   if p.stat().st_size>32*1024*1024:return dict(state='unknown',reason='image_file_limit_32MiB',computed=False)
   with warnings.catch_warnings():
    warnings.simplefilter('error',Image.DecompressionBombWarning)
    with Image.open(p) as im:
     if im.format not in ['PNG','JPEG']:return dict(state='unknown',reason='unsupported_image_format_PNG_JPEG_only',computed=False)
     if im.width*im.height>16_000_000:return dict(state='unknown',reason='decoded_image_limit_16M_pixels',computed=False)
     x,y,w,h=a[region]
     if x+w>im.width or y+h>im.height:raise ValueError('image ROI out of bounds: '+region)
     if getattr(im,'n_frames',1)!=1:return dict(state='unknown',reason='animated_image_not_supported',computed=False)
     if im.getexif().get(274,1)!=1:return dict(state='unknown',reason='EXIF_orientation_requires_explicit_normalization',computed=False)
     # Explicit white alpha composite; stored 8-bit RGB channels, no hidden color/contrast normalization.
     rgba=im.crop((x,y,x+w,y+h)).convert('RGBA');bg=Image.new('RGBA',rgba.size,(255,255,255,255));bg.alpha_composite(rgba);crops.append(bg.convert('RGB'))
   hashes.append(hashlib.sha256(p.read_bytes()).hexdigest())
  except FileNotFoundError:return dict(state='unknown',reason='image_material_missing:'+key,computed=False)
  except (Image.DecompressionBombError,Image.DecompressionBombWarning):return dict(state='unknown',reason='unsafe_image_dimensions',computed=False)
  except OSError:return dict(state='unknown',reason='image_unreadable:'+key,computed=False)
 ref,cand=crops;original_size=list(cand.size)
 if cand.size!=ref.size:cand=cand.resize(ref.size,Image.Resampling.BILINEAR)
 rb=ref.tobytes();cb=cand.tobytes();n=len(rb)
 mae=sum(abs(x-y) for x,y in zip(rb,cb))/(n*255)
 mse=sum((x-y)**2 for x,y in zip(rb,cb))/(n*255**2)
 return dict(state='computed',computed=True,asset_id=a['asset_id'],mae=mae,mse=mse,metric_range=[0,1],reference_region=a['reference_region'],candidate_region=a['candidate_region'],transform=a['transform'],reference_grid=list(ref.size),candidate_crop_grid=original_size,resampling='fixed bilinear candidate-to-reference grid',channels='stored 8-bit RGB, alpha composited on white; no ICC/gamma conversion',search='none',sha256=hashes,scope='local auxiliary metric only; no universal threshold and no D17 pass decision',identity_evidence=a['identity_evidence']['refs'])

def validate_chart_case(a):
 for t in a['tolerances'].values():
  if type(t) not in (int,float) or not math.isfinite(t) or t<0:raise ValueError('invalid explicit chart tolerance')
 for side in ['reference','candidate']:
  data=a[side]
  if data is None:continue
  ids=[s['id'] for s in data['series']]
  if len(ids)!=len(set(ids)):raise ValueError('duplicate chart series ID')
  for s in data['series']:
   points=s['points'];pids=[p['id'] for p in points]
   if len(pids)!=len(set(pids)):raise ValueError('duplicate chart point ID')
   for p in points:
    if any(type(p[k]) not in (int,float) or not math.isfinite(p[k]) for k in ['x','y']):raise ValueError('nonfinite chart value')
 matches=a['series_matches']
 if len({m['ref'] for m in matches})!=len(matches) or len({m['candidate'] for m in matches})!=len(matches):raise ValueError('chart series mapping is not one-to-one')
 for m in matches:
  pm=m['point_matches']
  if len({x['ref'] for x in pm})!=len(pm) or len({x['candidate'] for x in pm})!=len(pm):raise ValueError('chart point mapping is not one-to-one')
  for side,key in [('reference','ref'),('candidate','candidate')]:
   if a[side] is None:continue
   s=next((s for s in a[side]['series'] if s['id']==m[key]),None)
   if s is None:raise ValueError('unknown series mapping ID')
   if any(p[key] not in {v['id'] for v in s['points']} for p in pm):raise ValueError('unknown point mapping ID')

def compare_chart(a):
 validate_chart_case(a)
 if not attested(a['evidence']):return dict(data_status='unknown',reason='chart_data_not_attested',computed=False)
 if a['reference'] is None or a['candidate'] is None:return dict(data_status='unknown',reason='underlying_data_missing; visual review remains available',computed=False)
 ref=a['reference'];cand=a['candidate'];errors=[];deviations=[];complete=True
 for axis in ['x','y']:
  for field in ['scale','unit']:
   if ref['axes'][axis][field]!=cand['axes'][axis][field]:errors.append(dict(property=f'axes.{axis}.{field}',reference=ref['axes'][axis][field],candidate=cand['axes'][axis][field]))
 rr={s['id']:s for s in ref['series']};cc={s['id']:s for s in cand['series']}
 if not rr or not cc:complete=False
 if {m['ref'] for m in a['series_matches']}!=rr.keys() or {m['candidate'] for m in a['series_matches']}!=cc.keys():complete=False
 for m in a['series_matches']:
  r=rr[m['ref']];c=cc[m['candidate']]
  for field in ['semantic_id','legend_key']:
   if r[field]!=c[field]:errors.append(dict(property=f'series.{r["id"]}.{field}',reference=r[field],candidate=c[field]))
  rp={p['id']:p for p in r['points']};cp={p['id']:p for p in c['points']}
  if not rp or not cp or {p['ref'] for p in m['point_matches']}!=rp.keys() or {p['candidate'] for p in m['point_matches']}!=cp.keys():complete=False
  # Compare values only when units/scales/semantic identities match. Never convert or infer correspondences.
  compatible=ref['axes']==cand['axes'] and r['semantic_id']==c['semantic_id']
  for pair in m['point_matches']:
   for axis in ['x','y']:
    if not compatible:continue
    rv=rp[pair['ref']][axis];cv=cp[pair['candidate']][axis];tol=a['tolerances'][axis+'_abs']
    with localcontext() as ctx:
     ctx.prec=700;exact_delta=abs(Decimal(str(rv))-Decimal(str(cv)));exceeds=exact_delta>Decimal(str(tol))
    delta=float(exact_delta)
    if not math.isfinite(delta):raise ValueError('chart difference exceeds finite result range')
    record=dict(series_ref=r['id'],series_candidate=c['id'],point_ref=pair['ref'],point_candidate=pair['candidate'],axis=axis,reference=rv,candidate=cv,absolute_error=delta,tolerance=tol)
    deviations.append(record)
    if exceeds:errors.append(dict(property='point_value',**record))
 return dict(data_status='fail' if errors else 'pass' if complete else 'unknown',computed=True,complete_mapping=complete,errors=errors,deviations=deviations,tolerances=a['tolerances'],evidence=a['evidence']['refs'],scope='provided numerical values, axis scale/unit and legend/series mapping only; rendered chart still needs review',reason='explicit_data_metadata_comparison')
