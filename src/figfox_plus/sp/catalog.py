"""Executable geometry registry and model-facing instruction cards."""
import json
from .geometry import CONSTRUCTORS

_CARDS={
 'rect':('Four edges form a rectangle; width and height run along local horizontal and vertical axes.',['Locate the top-left corner.','Specify width, height, and fill color; the whole unit is positioned by TP.'],
         {'x':'number','y':'number','width':'positive','height':'positive','fill':'color'},
         {'shape':'rect','x':0,'y':0,'width':40,'height':20},'width/height > 0'),
 'ellipse':('Center and two semi-axes define an ellipse.',['Determine the center.','Determine horizontal and vertical radii; do not mistakenly substitute width/height for radii.'],
            {'cx':'number','cy':'number','rx':'positive','ry':'positive','fill':'color'},
            {'shape':'ellipse','cx':20,'cy':10,'rx':15,'ry':7},'rx/ry > 0'),
 'polygon':('At least three vertices connected in perimeter order form a closed polygon.',['Determine vertex order along the perimeter.','Pass points; the code closes the contour.'],
            {'points':'list of [x,y]','fill':'color'},
            {'shape':'polygon','points':[[0,0],[30,0],[15,20]]},'at least 3 finite points; non-self-intersecting'),
 'cuboid':('The main face is defined by origin, u, and v; depth describes the depth direction. Two outer adjacent faces reuse main face corners and the depth vector, sharing edges with the main face.',
           ['Identify one corner of the main face as origin and two edge vectors u/v.','Identify depth direction and length from reference, using depth_vector(length,angle) or explicit depth.',
            'Select colors for each face; code chooses two visible adjacent faces based on depth direction.','Treat as a single geometric object, positioned by TP.'],
           {'origin':'[x,y]','u':'[dx,dy]','v':'[dx,dy]','depth':'[dx,dy] OR omit and supply depth_length/depth_angle',
            'depth_length':'positive; alternative to depth','depth_angle':'degrees; positive toward upper right',
            'colors':'optional front/top/right/bottom/left -> color'},
           {'shape':'cuboid','origin':[0,20],'u':[30,0],'v':[0,30],'depth':[10,-10]},
           'non-collinear u/v; depth nonzero and shows two adjacent faces'),
 'cylinder':('A cylinder consists of a side path and a top ellipse; the top ellipse shares center and radius with the side.',
             ['Determine top face center x/y, radius, and ry.','Specify height; code connects the side and bottom arc.'],
             {'x':'number','y':'number','radius':'positive','height':'positive','ry':'optional positive'},
             {'shape':'cylinder','x':20,'y':10,'radius':15,'height':40},'radius/height/ry > 0'),
 'array':('The same sub-object forms a regular array along two step vectors; each unit retains a stable component index.',
          ['Select and specify an item.','Specify rows/cols and step_x/step_y; step is the offset between adjacent origins, not edge-to-edge clearance.'],
          {'rows':'int 1..100','cols':'int 1..100','step_x':'[dx,dy]','step_y':'[dx,dy]',
           'item':'rect/ellipse/polygon/cuboid/cylinder spec'},
          {'shape':'array','rows':2,'cols':2,'step_x':[35,0],'step_y':[0,40],
           'item':{'shape':'cuboid','origin':[0,15],'u':[20,0],'v':[0,20],'depth':[7,-7]}},
          'rows*cols <= 400; nested arrays unsupported'),
 'cluster':('Multiple cuboids have distinct constructor parameters; list order is the occlusion order, drawing rear elements first and front elements last.',
            ['Identify position, projection, and size of each member individually.','Populate items in reference occlusion order; do not infer general occlusion from x+y.'],
            {'items':'list of cuboid specs','order':'as_given'},
            {'shape':'cluster','items':[{'shape':'cuboid','origin':[0,15],'u':[20,0],'v':[0,20],'depth':[7,-7]}]},
            '1..400 cuboids; explicit order only'),
 'lattice':('Three basis vectors define a parallelepiped; default is a hollow grid; flat fills on visible faces can be specified using colors.',
            ['Determine origin/u/v/depth and cell division counts divisions for each direction.','Choose grid=none/faces/volume; typically use faces.',
             'When vertical thin slices are needed, provide fractions in (0,1) along u in slices; do not substitute solid blocks for hollow boxes.'],
            {'origin':'[x,y]','u':'[dx,dy]','v':'[dx,dy]','depth':'[dx,dy]',
             'divisions':'[nu,nv,nd]','shell':'optional boolean: boundary edges only, NOT filled faces; default true',
             'grid':'none|faces|volume','slices':'list of fractions in (0,1)',
             'stroke':'optional edge color','stroke_width':'positive finite edge width',
             'colors':'optional per-face front/top/right/bottom/left fills; enables visible-face grid only',
             'fill':'optional uniform face fill; colors overrides per face','dash':'optional SVG dash pattern; empty string for solid',
             'slice_fill':'optional slice fill','slice_opacity':'optional slice opacity'},
            {'shape':'lattice','origin':[0,20],'u':[50,0],'v':[0,60],'depth':[20,-20],
             'divisions':[3,4,3],'grid':'faces','slices':[0.25,0.6]},
            'non-degenerate projection; divisions 1..100; slices along u only; colors/fill provide flat faces with visible-only grid; texture unsupported: use vector_asset for complex texture'),
}

CATALOG={name:{'name':name,'forward_description':card[0],'inverse_steps':card[1],
                'parameters':card[2],'examples':[card[3]],'preconditions':card[4],
                'callable':CONSTRUCTORS[name],'anchors':['left','right','top','bottom','center'],
                'counterexamples':['Do not treat local coordinates as full-figure coordinates.','Do not treat combined components as unrelated objects.'],
                'limitations':'This is a parallel-projection construction; perspective and unknown occlusion are not recovered automatically. Actual visible boundaries must be verified through render measurements.'}
         for name,card in _CARDS.items()}


def serializable_catalog():
    return [{k:v for k,v in entry.items() if k!='callable'} for entry in CATALOG.values()]


def manual():
    lines=['# SP Object Manual','',
           'Generated from the executable registry. Coordinates are object-local coordinates; object matrix maps to parent coordinates.',
           'Object kind is restricted to frame/geometry/text/formula/arrow/picture/group/vector_asset. rect/cuboid/array and others must be written in data.shape of geometry or frame, never in kind.',
           'Color parameters are derived from the original figure, not restricted by a fixed color palette. Geometric correctness alone does not mean the result passes fidelity checking against the original figure.','',
           'depth_vector(length, angle_degrees) = (length*cos(angle), -length*sin(angle)).',
           'Positive angles point toward upper right. A square front face is a special case of oblique projection; isometric projection may use slanted u/v.',
           'Selection rule: cuboid generates only three flat faces, not a grid; grid cuboids / Rubik\'s-cube-like structures must use lattice with explicit divisions, face fills, and grid. Noise texture is not a grid; complex multi-object regions or textures should use the asset route. Unknown parameters will be rejected; missing construction details will not be inferred automatically.','']
    for name,e in CATALOG.items():
        example=e['examples'][0]
        if name in CONSTRUCTORS:
            example={'id':'example','name':'example geometry','kind':'geometry','data':example}
        lines.extend([f'## {name}',f'Forward composition: {e["forward_description"]}','Inverse construction:'])
        lines.extend(f'{i}. {x}' for i,x in enumerate(e['inverse_steps'],1))
        lines.extend(['Parameters: '+json.dumps(e['parameters'],ensure_ascii=False),
                      'Preconditions: '+e['preconditions'], 'Example:', '```json',
                      json.dumps(example,ensure_ascii=False,indent=2),'```',
                      'Limitations: '+e['limitations'],'Counterexamples: '+'; '.join(e['counterexamples']),''])
    return '\n'.join(lines)


def _compile_example(obj):
    from .compiler import compile_scene
    return compile_scene({'version':'plus-0.1','canvas':{'width':320,'height':200},
                          'objects':[obj],'relations':[],'assets':[]})


_CONTENT_CARDS={
 'text':('Text remains a single text object; font size and baseline position define typesetting, while matrix controls overall orientation.',
         ['Identify original text, font size, and font family.','Specify first-line baseline with x/y, choose anchor as start/middle/end; specify rotation in object matrix.'],
         {'text':'string','x':'baseline x','y':'baseline y','font_size':'positive','font_family':'font stack','anchor':'start|middle|end','fill':'color','style':'font-weight/font-style/fill/letter-spacing/text-decoration'},
         {'text':'Face','x':20,'y':40,'font_size':24},
         'Single-line; fonts must be available locally; do not compress text using textLength.'),
 'formula':('TeX generates paths within the same object locally; radicals, subscripts/superscripts, and fractions move with the object as a whole unit.',
            ['Extract TeX structure from the original figure.','Specify x/y as the top-left corner of the formula viewport and font_size; move the overall matrix, not individual glyphs.'],
            {'tex':'TeX string','x':'viewport left','y':'viewport top','font_size':'positive'},
            {'tex':r'\sqrt{x^2+y_1}','x':20,'y':20,'font_size':28},
            'Supports local MathJax base/ams/newcommand; unsupported commands raise errors; cannot generate empty placeholder objects as substitutes.'),
 'arrow':('The shaft path connects the two endpoints. Each marker triangle tip coincides with its corresponding path endpoint, with the head base behind the tip.',
          ['Distinguish line/polyline/rounded/cubic from the reference; do not round every corner.','Populate waypoints sequentially, choose head_length/head_width and double.','For rounded corners, cap radius at half the adjacent segment length; the Q control point is the original corner point. Connected object recalculation is handled by TP.'],
          {'waypoints':'ordered [x,y] points; cubic exactly four','route':'line|polyline|rounded|cubic','radius':'nonnegative','head_length':'positive','head_width':'positive','double':'boolean','stroke_width':'positive','stroke':'color','start':'optional {object_id,anchor}','end':'optional {object_id,anchor}'},
          {'waypoints':[[20,30],[100,30],[100,90]],'route':'rounded','radius':8,'head_length':10,'head_width':8},
          'Rejects zero-length segments; cubic uses first and last control points to determine end tangents. Currently does not automatically avoid obstacles; TP linkage supports only line, other routes require explicit rerouting. Indices provide tip/base_center/shaft_endpoint; shaft endpoint coincides with the tip and is covered by the head.'),
 'frame':('The base frame is an independent geometric object with an ID; content references it via parent_id; do not mistake content ID for frame ID.',
          ['First determine frame extent and independent ID.','Choose an existing shape constructor; supplemental frames also register independent IDs, with child objects drawn after the frame itself.'],
          {'shape':'registered geometry shape','other':'see matching geometry card'},
          {'shape':'rect','x':10,'y':10,'width':180,'height':100,'fill':'none'},
          'Currently uses existing geometry constructors; does not accept arbitrary native path strings.'),
 'group':('A group provides only a shared coordinate system and identity; child objects belong to it via parent_id without drawing additional placeholder boxes.',
          ['Create a group with an independent ID and empty data.','Point member parent_id to this ID; write shared transformations into the group matrix.'],
          {},{},'An empty group has no visible area; do not treat it as completed geometry.')}
for _kind,_card in _CONTENT_CARDS.items():
    CATALOG[_kind]={'name':_kind,'forward_description':_card[0],'inverse_steps':_card[1],
      'parameters':_card[2],'examples':[{'id':'example','name':'example','kind':_kind,'data':_card[3]}],
      'callable':_compile_example,'preconditions':'Valid object ID; finite coordinates; references an existing parent object.',
      'anchors':['left','right','top','bottom','center'],
      'counterexamples':['Do not mistake text baseline for formula top-left corner.','Do not claim original-figure fidelity based merely on successful rendering.'],
      'limitations':_card[4]}
