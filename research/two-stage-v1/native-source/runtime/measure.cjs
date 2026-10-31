const fs=require('fs');
const {chromium}=require(process.env.PLUS_PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
 const input=JSON.parse(fs.readFileSync(0,'utf8'));
 const browser=await chromium.launch({...(process.env.PLUS_CHROMIUM ? {executablePath:process.env.PLUS_CHROMIUM} : {}),headless:true});
 try {
  const context=await browser.newContext({javaScriptEnabled:false,viewport:{width:1600,height:1200}});
  await context.route('**/*',r=>r.abort());
  const page=await context.newPage();
  await page.setContent('<!doctype html><html><body style="margin:0">'+input.svg+'</body></html>');
  const result=await page.evaluate(async(index)=>{
   await document.fonts.ready;
   const bounds=pts=>({left:Math.min(...pts.map(p=>p.x)),top:Math.min(...pts.map(p=>p.y)),right:Math.max(...pts.map(p=>p.x)),bottom:Math.max(...pts.map(p=>p.y))});
   const output={};
   for(const node of document.querySelectorAll('svg *')) {
    const s=getComputedStyle(node);
    if(s.filter!=='none'||s.clipPath!=='none'||s.maskImage!=='none') throw Error('unsupported bounds effect: filter/clip/mask');
    if(s.markerStart!=='none'||s.markerMid!=='none'||s.markerEnd!=='none') {
     const owner=node.closest('[data-sp-owner]')?.getAttribute('data-sp-owner');
     if(!owner||!index[owner]?.head_triangles||s.markerMid!=='none') throw Error('unsupported unmodeled marker');
    }
   }
   for(const [id,meta] of Object.entries(index)) {
    const el=document.getElementById(meta.node_id);
    if(!el) throw Error('missing measured node '+id);
    const b=el.getBBox(),m=el.getCTM();
    const map=(x,y)=>new DOMPoint(x,y).matrixTransform(m);
    const geometry=bounds([map(b.x,b.y),map(b.x+b.width,b.y),map(b.x,b.y+b.height),map(b.x+b.width,b.y+b.height)]);
    let pad=0;
    for(const node of [el,...el.querySelectorAll('*')]) {
     if(!node.getCTM || node.closest('defs')) continue;
     const s=getComputedStyle(node),t=node.getCTM();
     if(s.stroke!=='none') pad=Math.max(pad,parseFloat(s.strokeWidth)/2*Math.hypot(t.a,t.b,t.c,t.d)*Math.max(1,parseFloat(s.strokeMiterlimit)||1));
    }
    const paint={left:geometry.left-pad,top:geometry.top-pad,right:geometry.right+pad,bottom:geometry.bottom+pad};
    for(const child of Object.values(index)) {
     const childNode=document.getElementById(child.node_id);
     if(!childNode || !el.contains(childNode)) continue;
     for(const triangle of child.head_triangles||[]) {
     const h=bounds(triangle.map(p=>new DOMPoint(...p).matrixTransform(childNode.getCTM())));
     paint.left=Math.min(paint.left,h.left);paint.top=Math.min(paint.top,h.top);
     paint.right=Math.max(paint.right,h.right);paint.bottom=Math.max(paint.bottom,h.bottom);
     }
    }
    output[id]={geometry_bbox:geometry,paint_bbox:paint,bounds_source:'browser_getBBox_transformed_corners',paint_bounds_conservative:true};
   }
   return output;
  },input.index);
  if(input.png) await page.locator('body > svg').screenshot({path:input.png});
  process.stdout.write(JSON.stringify(result));
 } finally {await browser.close();}
})().catch(e=>{process.stderr.write(String(e));process.exit(1)});
