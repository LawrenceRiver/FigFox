const fs=require('fs');
const {chromium}=require(process.env.PLUS_PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
 const input=JSON.parse(fs.readFileSync(0,'utf8'));
 const browser=await chromium.launch({...(process.env.PLUS_CHROMIUM ? {executablePath:process.env.PLUS_CHROMIUM} : {}),headless:true});
 try {
 const context=await browser.newContext({javaScriptEnabled:false,viewport:{width:1800,height:1400}});
 await context.route('**/*',r=>r.abort());const page=await context.newPage();
 await page.setContent('<!doctype html><html><body style="margin:0">'+input.svg+'</body></html>');
 const result=await page.evaluate(async()=>{
  await document.fonts.ready; await Promise.all([...document.images].map(x=>x.decode().catch(()=>{})));
  const root=document.querySelector('body > svg');const inverse=root.getCTM().inverse();
  const mat=m=>[m.a,m.b,m.c,m.d,m.e,m.f];
  const bbox=(b,m)=>{const p=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(p=>new DOMPoint(...p).matrixTransform(m));return {left:Math.min(...p.map(v=>v.x)),top:Math.min(...p.map(v=>v.y)),right:Math.max(...p.map(v=>v.x)),bottom:Math.max(...p.map(v=>v.y))}};
  const objects={};for(const el of root.querySelectorAll('[id]')){
   if(!el.getBBox||el.closest('defs,marker,symbol,clipPath,mask'))continue;
   const m=inverse.multiply(el.getCTM());const b=el.getBBox();const s=getComputedStyle(el);
   const box=bbox(b,m);const sw=s.stroke==='none'?0:parseFloat(s.strokeWidth)||0;
   const pad=sw/2*Math.max(Math.hypot(m.a,m.b),Math.hypot(m.c,m.d))*Math.max(1,parseFloat(s.strokeMiterlimit)||1);
   const paint={left:box.left-pad,top:box.top-pad,right:box.right+pad,bottom:box.bottom+pad};
   const effects=['filter','clipPath','maskImage','markerStart','markerMid','markerEnd'].filter(k=>s[k]&&s[k]!=='none');
   const parent=el.parentElement;const pm=parent.getCTM?inverse.multiply(parent.getCTM()):new DOMMatrix();
   objects[el.id]={tag:el.localName,parent_id:parent===root?null:parent.id||null,geometry_bbox:box,paint_bbox:paint,
    local_bbox:{x:b.x,y:b.y,width:b.width,height:b.height},world:mat(m),parent_world:mat(pm),
    text:el.localName==='text'?el.textContent:null,effects,bounds_conservative:true,bounds_complete:effects.length===0};
  }
  const v=root.viewBox.baseVal;return {canvas:{x:v.x,y:v.y,width:v.width||root.width.baseVal.value,height:v.height||root.height.baseVal.value},objects};
 });
 if(input.png)await page.locator('body > svg').screenshot({path:input.png});
 process.stdout.write(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{process.stderr.write(String(e));process.exit(1)});
