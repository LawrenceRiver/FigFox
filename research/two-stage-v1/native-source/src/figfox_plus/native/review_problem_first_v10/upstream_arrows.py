"""Freeze explicit original-image SAM evidence, never interpret it as truth.

No directory discovery, provider calls, current-SVG TP, or answer data is used.
All model-visible fields are selected explicitly; source paths remain provenance.
"""
from pathlib import Path
import hashlib
import json
import math
import shutil
from PIL import Image, ImageOps


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _file(value):
    if isinstance(value,dict):
        path=Path(value['path']).expanduser().resolve(strict=True)
        if value.get('sha256') is not None and _sha(path)!=value['sha256']:raise ValueError('arrow evidence asset hash mismatch')
    elif isinstance(value,str):path=Path(value).expanduser().resolve(strict=True)
    else:raise ValueError('explicit evidence file required')
    if not path.is_file():raise ValueError('evidence must be a regular file')
    return path


def _rgb(path):
    with Image.open(path) as image:
        rgba=ImageOps.exif_transpose(image).convert('RGBA')
        background=Image.new('RGBA',rgba.size,'white');background.alpha_composite(rgba)
        return background.convert('RGB')


def _unavailable(reason,provenance=None):
    return {'model_context':{'status':'unavailable','reason':reason,'arrows':[],
                            'coordinate_domain':'original_image_pixels','is_ground_truth':False},
            'image_assets':[],'provenance':provenance or {}}


def freeze_arrow_evidence(spec, original_asset, output_dir):
    """spec={sam_manifest: path, head_evidence?: path}; assets may carry sha256.

    Returns model_context without local paths or raw SAM text, image_assets as
    frozen {asset_id,path,sha256,dimensions}, and host-only provenance. Missing
    SAM is unavailable; claimed but mismatched source/assets fail closed.
    """
    original_path=_file(original_asset)
    if not isinstance(original_asset,dict) or original_asset.get('sha256')!=_sha(original_path):raise ValueError('original asset must carry its verified sha256')
    if not spec or not spec.get('sam_manifest'):return _unavailable('no_explicit_upstream_sam')
    manifest_path=_file(spec['sam_manifest']);manifest=json.loads(manifest_path.read_text())
    provenance={'sam_manifest':str(manifest_path),'sam_manifest_sha256':_sha(manifest_path),
                'original_asset_sha256':original_asset['sha256'],'sam_source_hash':manifest.get('source_hash')}
    if manifest.get('mock') is not False:raise ValueError('only real upstream SAM evidence is accepted')
    if manifest.get('status',{}).get('sam')!='ok':return _unavailable('upstream_sam_unavailable',provenance)
    catalog_path=_file(manifest.get('catalog_path'));catalog=json.loads(catalog_path.read_text())
    if catalog.get('original_sha256')!=manifest.get('source_hash'):raise ValueError('SAM source and catalog identity disagree')
    request_path=_file(str(catalog_path.parent/'request_image.png'))
    if _sha(request_path)!=catalog.get('canonical_sha256'):raise ValueError('SAM request image hash mismatch')
    original=_rgb(original_path);request=_rgb(request_path)
    if list(request.size)!=catalog.get('image_size'):raise ValueError('SAM image size differs from catalog')
    if original.size!=request.size or original.tobytes()!=request.tobytes():raise ValueError('SAM request is not the same original image')
    binding='file_sha256' if manifest['source_hash']==original_asset['sha256'] else 'pixel_equivalent'
    provenance.update(original_binding=binding,canonical_request_sha256=_sha(request_path),
                      request_image=str(request_path),catalog_path=str(catalog_path),catalog_sha256=_sha(catalog_path),
                      canonical_rgb_pixel_sha256=hashlib.sha256(original.tobytes()).hexdigest(),image_size=list(original.size))
    head_map={}
    if spec.get('head_evidence'):
        head_path=_file(spec['head_evidence']);heads=json.loads(head_path.read_text())
        if not isinstance(heads,list):raise ValueError('head evidence must be an array')
        for head in heads:
            if not isinstance(head,dict) or not isinstance(head.get('id'),str) or head['id'] in head_map:raise ValueError('invalid or duplicate head evidence identity')
            head_map[head['id']]=head
        provenance.update(head_evidence=str(head_path),head_evidence_sha256=_sha(head_path))
    entries=manifest.get('assets')
    if not isinstance(entries,list):raise ValueError('SAM assets must be an array')
    catalog_assets=catalog.get('assets',[]);validated=[];seen=set()
    for asset in entries:
        if asset.get('role')!='arrow_hint':continue
        aid=asset.get('id');raw=asset.get('raw',{})
        if not isinstance(aid,str) or aid in seen or asset.get('method')!='sam' or asset.get('source_hash')!=manifest['source_hash']:raise ValueError('invalid SAM arrow identity')
        seen.add(aid)
        if not any(all(c.get(k)==raw.get(k) for k in ('asset_path','sha256','mask_path','mask_sha256','bbox')) for c in catalog_assets):raise ValueError('arrow not present in source catalog')
        bbox=raw.get('bbox')
        if not isinstance(bbox,list) or len(bbox)!=4 or any(type(v)!=int for v in bbox):raise ValueError('SAM bbox must be integer original pixels')
        l,t,r,b=bbox
        if not (0<=l<r<=original.width and 0<=t<b<=original.height):raise ValueError('SAM bbox outside original')
        crop=[l,t,r-l,b-t]
        if asset.get('source_crop')!=crop:raise ValueError('source_crop and original bbox disagree')
        asset_path=_file(asset.get('path'));mask_path=_file(str(catalog_path.parent/raw['mask_path']))
        catalog_crop=_file(str(catalog_path.parent/raw['asset_path']))
        if asset_path!=catalog_crop or _sha(asset_path)!=asset.get('asset_hash') or _sha(asset_path)!=raw.get('sha256'):raise ValueError('SAM arrow crop hash mismatch')
        if _sha(mask_path)!=raw.get('mask_sha256'):raise ValueError('SAM mask hash mismatch')
        with Image.open(mask_path) as mask_file:mask=mask_file.convert('L')
        if mask.size!=original.size:raise ValueError('SAM mask must be original full-canvas size')
        expected=request.convert('RGBA');expected.putalpha(mask);expected=expected.crop(bbox)
        with Image.open(asset_path) as crop_file:
            if crop_file.format!='PNG':raise ValueError('SAM crop must be PNG')
            actual=crop_file.convert('RGBA')
        if actual.size!=expected.size or actual.tobytes()!=expected.tobytes():raise ValueError('SAM crop pixels differ from original plus mask')
        metadata={}
        if aid in head_map:
            head=head_map[aid]
            if head.get('source_crop')!=crop:raise ValueError('head evidence crop mismatch')
            count=head.get('detected_heads');pixels=head.get('head_pixels')
            if type(count)!=int or count<0:raise ValueError('invalid candidate head count')
            if pixels is not None and (not isinstance(pixels,list) or len(pixels)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in pixels)):raise ValueError('invalid head pixel size')
            metadata={'detected_heads':count,'head_pixels':pixels,'head_evidence_basis':'local_contour_corner_candidates'}
        validated.append((asset_path,mask_path,crop,metadata,aid))
    if set(head_map)-seen:raise ValueError('head evidence contains unknown SAM arrow identities')
    if not validated:return _unavailable('no_upstream_arrow_candidates',provenance)
    output=Path(output_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    model_arrows=[];images=[];sources=[]
    for index,(asset_path,mask_path,crop,metadata,aid) in enumerate(validated):
        key=f'sam_arrow_{index:04d}';dest=output/f'{key}.png';mask_dest=output/f'{key}-mask.png'
        shutil.copyfile(asset_path,dest);shutil.copyfile(mask_path,mask_dest)
        image_asset={'asset_id':key,'path':str(dest),'sha256':_sha(dest),'dimensions':crop[2:]}
        images.append(image_asset)
        model_arrows.append({'asset_id':key,'source_crop':crop,**metadata})
        sources.append({'asset_id':key,'upstream_id':aid,'source_asset':str(asset_path),'source_mask':str(mask_path),'asset_sha256':image_asset['sha256'],'frozen_mask':str(mask_dest),'mask_sha256':_sha(mask_dest)})
    provenance['assets']=sources
    return {'model_context':{'status':'available','coordinate_domain':'original_image_pixels',
                             'source_crop_format':'xywh','is_ground_truth':False,
                             'usage':'Independent upstream SAM candidates for secondary original-image localization. May miss or falsely detect arrows. Head counts are corner candidates, not true arrow counts. Do not transfer these coordinates to current SVG TP.',
                             'arrows':model_arrows},'image_assets':images,'provenance':provenance}
