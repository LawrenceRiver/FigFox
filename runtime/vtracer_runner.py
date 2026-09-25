import json,sys,vtracer
p=json.load(sys.stdin)
vtracer.convert_image_to_svg_py(p['source'],p['target'],**p['parameters'])
