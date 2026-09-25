"""Compile supported semantic objects to SVG, preserving ownership and hierarchy."""
import xml.etree.ElementTree as ET
from ..contracts import validate_scene
from ..assets import raster_part,vector_element
from .geometry import construct
from .content import content_element
from .arrows import route_path, head_triangle

SVG='http://www.w3.org/2000/svg'
ET.register_namespace('',SVG)


def compile_scene(scene: dict) -> tuple[str,dict]:
    errors=[e for e in validate_scene(scene) if not e['path'].startswith('relations')]
    if errors: raise ValueError(errors)
    root=ET.Element(f'{{{SVG}}}svg',{'width':str(scene['canvas']['width']),
           'height':str(scene['canvas']['height']),
           'viewBox':f'0 0 {scene["canvas"]["width"]} {scene["canvas"]["height"]}'})
    by_id={o['id']:o for o in scene['objects']};groups={};index={}
    def group(oid):
        if oid in groups: return groups[oid]
        obj=by_id[oid];parent=group(obj['parent_id']) if obj.get('parent_id') else root
        g=ET.SubElement(parent,f'{{{SVG}}}g',{'id':f'sp.obj.{oid}','data-sp-owner':oid,
                'data-sp-kind':obj['kind'],'transform':'matrix('+ ' '.join(f'{n:g}' for n in obj.get('matrix',[1,0,0,1,0,0]))+')'})
        ET.SubElement(g,f'{{{SVG}}}title').text=obj['name']
        groups[oid]=g
        return g
    for obj in scene['objects']:
        oid=obj['id'];g=group(oid)
        extra={}
        if obj['kind']=='group': parts=[]
        elif obj['kind'] in ('geometry','frame'): parts=construct(obj['data'])
        elif obj['kind']=='picture':parts=[raster_part(obj['data'],scene.get('assets',[]))]
        elif obj['kind']=='vector_asset':
            parts=[{'part':'vector','attrs':{},'tag':'g','points':[],
                    'element':vector_element(obj['data'],scene.get('assets',[]),oid)}]
        elif obj['kind'] in ('text','formula'):
            element=content_element(obj['kind'],obj['data'])
            parts=[{'part':'content','attrs':{},'tag':'g','points':[], 'element':element}]
        elif obj['kind']=='arrow':
            d=obj['data'];points=[list(map(float,p)) for p in d['waypoints']]
            path=route_path(points,d.get('route','polyline'),d.get('radius',8))
            length=float(d.get('head_length',10));width=float(d.get('head_width',8))
            heads=[head_triangle(points[-1],points[-2],length,width)]
            if d.get('double'): heads.append(head_triangle(points[0],points[1],length,width))
            marker_id=f'sp.marker.{oid}.head'
            defs=ET.SubElement(root,f'{{{SVG}}}defs')
            marker=ET.SubElement(defs,f'{{{SVG}}}marker',{'id':marker_id,'viewBox':f'0 0 {length:g} {width:g}',
                'markerWidth':str(length),'markerHeight':str(width),'refX':str(length),'refY':str(width/2),
                'orient':'auto-start-reverse','markerUnits':'userSpaceOnUse','overflow':'visible'})
            color=d.get('stroke','#222222')
            ET.SubElement(marker,f'{{{SVG}}}path',{'d':f'M 0 0 L {length:g} {width/2:g} L 0 {width:g} Z','fill':color})
            attrs={'d':path,'fill':'none','stroke':color,'stroke-width':str(d.get('stroke_width',2)),
                   'marker-end':f'url(#{marker_id})','stroke-linejoin':'round'}
            if d.get('double'): attrs['marker-start']=f'url(#{marker_id})'
            parts=[{'part':'body','tag':'path','attrs':attrs,'points':points}]
            extra={'head_triangles':heads,'arrow_anchors':{'start_tip':points[0],'end_tip':points[-1]}}
            extra['arrow_anchors']['end_base_center']=[(heads[0][1][i]+heads[0][2][i])/2 for i in range(2)]
            extra['arrow_anchors']['end_shaft_endpoint']=points[-1]
            extra['arrow_anchors']['start_shaft_endpoint']=points[0]
            if d.get('double'):
                extra['arrow_anchors']['start_base_center']=[(heads[1][1][i]+heads[1][2][i])/2 for i in range(2)]
        else: raise ValueError(f'unsupported compiler kind: {obj["kind"]}')
        # Preserve explicit primitive/arrow styling instead of silently dropping it.
        data=obj['data']
        if obj['kind']=='arrow' or (obj['kind'] in ('geometry','frame') and data.get('shape') in ('rect','ellipse','polygon')):
            for part in parts:
                for key,attribute in [('stroke_width','stroke-width'),('stroke_dasharray','stroke-dasharray'),('stroke_dashoffset','stroke-dashoffset')]:
                    if key in data:part['attrs'][attribute]=data[key]
                if part['tag']=='rect' and 'radius' in data and 'rx' not in data:
                    part['attrs']['rx']=data['radius']
        pids=[];pts=[]
        for position,part in enumerate(parts):
            pid=f'sp.part.{oid}.{part["part"]}'
            attrs={k:str(v) for k,v in part['attrs'].items()}
            attrs.update({'id':pid,'data-sp-owner':oid,'data-sp-part':part['part']})
            # A frame's own paint precedes its children even if scene input lists children first.
            element=part.get('element')
            if element is None: element=ET.Element(f'{{{SVG}}}{part['tag']}')
            element.attrib.update(attrs)
            g.insert(position+1,element)
            pids.append(pid);pts.extend(part['points'])
        bounds=None
        if pts:
            bounds={'left':min(p[0] for p in pts),'top':min(p[1] for p in pts),
                    'right':max(p[0] for p in pts),'bottom':max(p[1] for p in pts)}
        index[oid]={'node_id':g.get('id'),'part_ids':pids,'parent_id':obj.get('parent_id'),
                    'kind':obj['kind'],'name':obj['name'],'local_geometry_bounds':bounds,
                    'bounds_source':'constructor_geometry_excludes_stroke_not_world_measurement'}
        index[oid].update(extra)
    return ET.tostring(root,encoding='unicode'),index
