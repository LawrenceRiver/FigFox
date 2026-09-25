"""Human-authored constructor evidence. Never a model performance claim."""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET
from .state import new_run, write_json, PLUS_ROOT
from .sp.catalog import manual, serializable_catalog
from .sp.compiler import compile_scene, SVG


def gallery_scene():
    cube={'shape':'cuboid','origin':[55,70],'u':[60,0],'v':[0,60],'depth':[25,-20]}
    tiny={'shape':'cuboid','origin':[25,55],'u':[23,0],'v':[0,23],'depth':[9,-9]}
    colors=[('#e0e9b8','#f0f5d8','#b5c78d'),('#bdcfee','#e0e7f5','#829cbd'),
            ('#eed49a','#f9e8bf','#bd9b57'),('#b6d986','#ddebba','#7da453')]
    stack=[]
    for i in range(4):
        front,top,right=colors[i]
        stack.append({**tiny,'origin':[65-i*4,45+i*28],
                      'colors':{'front':front,'top':top,'right':right}})
    lat={'shape':'lattice','origin':[35,55],'u':[90,0],'v':[0,110],
         'depth':[30,-25],'divisions':[3,4,3],'grid':'faces','slices':[.23,.52,.78]}
    entries=[('right','Right projection',cube),
             ('left','Left projection',{**cube,'depth':[-25,-20]}),
             ('iso','Projected main face',{**cube,'origin':[30,80],'u':[55,27],'v':[0,65],'depth':[36,-20]}),
             ('cylinder','Cylinder',{'shape':'cylinder','x':85,'y':65,'radius':42,'height':90}),
             ('array','Array 2 x 3',{'shape':'array','rows':2,'cols':3,'step_x':[48,0],
                     'step_y':[0,60],'item':tiny}),
             ('stack','Explicit stacked order',{'shape':'cluster','items':stack}),
             ('shell','Shell only',{**lat,'grid':'none','slices':[]}),
             ('lattice','Faces and thin slices',lat)]
    objects=[]
    for n,(oid,name,data) in enumerate(entries):
        objects.append({'id':oid,'name':name,'kind':'geometry','parent_id':None,
                        'matrix':[1,0,0,1,10+(n%4)*220,20+(n//4)*220],
                        'data':copy.deepcopy(data)})
    return {'version':'plus-0.1','canvas':{'width':900,'height':460},
            'objects':objects,'relations':[],'assets':[]}


def run_gallery(out=None):
    import cairosvg
    run=new_run(Path(out) if out else PLUS_ROOT/'runs','offline')
    scene=gallery_scene();svg,index=compile_scene(scene)
    write_json(run/'scene.json',scene);write_json(run/'object-index.json',index)
    (run/'scene.svg').write_text(svg)
    # Labels decorate the test contact sheet, not the compiled product scene.
    root=ET.fromstring(svg)
    root.insert(0,ET.Element(f'{{{SVG}}}rect',{'width':'900','height':'460','fill':'white'}))
    for n,obj in enumerate(scene['objects']):
        ET.SubElement(root,f'{{{SVG}}}text',{'x':str(20+n%4*220),'y':str(28+n//4*220),
                      'font-size':'14','font-family':'sans-serif','fill':'#222',
                      'data-test-label':'true'}).text=obj['name']
    atlas=ET.tostring(root,encoding='unicode')
    (run/'atlas.svg').write_text(atlas)
    cairosvg.svg2png(bytestring=atlas.encode(),write_to=str(run/'atlas.png'))
    (run/'sp-manual.md').write_text(manual())
    write_json(run/'catalog.json',serializable_catalog())
    write_json(run/'NOTE.json',{'kind':'human-authored-constructor-gallery','model_requests':0,
               'quality_passed':False,'review_status':'needs_visual_review',
               'limitations':['No original-image reconstruction or DeepSeek inference tested.',
                              'Constructor local bounds exclude strokes; actual world measurement belongs to T3.']})
    return run
