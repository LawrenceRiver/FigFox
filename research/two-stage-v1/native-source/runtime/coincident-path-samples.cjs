// Separate offline sampler; never changes the live current-line-facts runtime.
const fs=require('fs');
const {chromium}=require(process.env.PLUS_PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
  const input=JSON.parse(fs.readFileSync(0,'utf8'));
  const browser=await chromium.launch({...(process.env.PLUS_CHROMIUM ? {executablePath:process.env.PLUS_CHROMIUM} : {}),headless:true});
  try {
    const context=await browser.newContext({javaScriptEnabled:false,serviceWorkers:'block'});
    await context.route('**/*',route=>route.abort());
    const page=await context.newPage();
    await page.setContent('<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:"></head><body></body></html>');
    const result=await page.evaluate(({ids,count,svg})=>{
      const parsed=new DOMParser().parseFromString(svg,'image/svg+xml');
      if(parsed.querySelector('parsererror') || parsed.documentElement.localName!=='svg' || parsed.documentElement.namespaceURI!=='http://www.w3.org/2000/svg')throw Error('Malformed SVG document or unsupported namespace');
      const root=document.importNode(parsed.documentElement,true);
      document.body.appendChild(root);
      if(typeof root.getCTM!=='function' || !root.getCTM())throw Error('SVG root CTM unavailable');
      const inv=root.getCTM().inverse(),all=[...root.querySelectorAll('*')];
      const records=[],unsupported=[];
      for(const id of ids){
        try{
          const e=id.startsWith('@node:')?all[Number(id.slice(6))]:all.find(e=>e.id===id);
          const length=e.getTotalLength(),m=inv.multiply(e.getCTM());
          const style=getComputedStyle(e),width=style.strokeWidth;
          if(style.vectorEffect && style.vectorEffect!=='none')throw Error('stroke envelope unsupported: vector-effect '+style.vectorEffect);
          if(!/^[+]?(?:\d*\.\d+|\d+\.?\d*)(?:e[+-]?\d+)?(?:px)?$/i.test(width))throw Error('stroke envelope unsupported: unresolved width '+width);
          const localWidth=parseFloat(width);
          // Largest singular value bounds the affine-transformed circular pen.
          // Exact for uniform scaling, conservative for anisotropic scale/shear.
          const aa=m.a*m.a+m.b*m.b,bb=m.c*m.c+m.d*m.d,ab=m.a*m.c+m.b*m.d;
          const maxScale=Math.sqrt((aa+bb+Math.hypot(aa-bb,2*ab))/2);
          if(!Number.isFinite(localWidth*maxScale)||localWidth<=0||maxScale<=0)throw Error('stroke envelope unsupported: invalid width/transform');
          const points=Array.from({length:count},(_,i)=>{
            const p=e.getPointAtLength(length*i/(count-1));
            const q=new DOMPoint(p.x,p.y).matrixTransform(m);return [q.x,q.y];
          });
          if(points.some(p=>p.some(v=>!Number.isFinite(v))))throw Error('nonfinite points');
          records.push({object_id:id,points,stroke_envelope:{local_width:localWidth,world_width_upper_bound:localWidth*maxScale,transform_max_scale:maxScale,basis:'local stroke width times largest singular value of current-world affine transform; conservative bound, not proof of painted overlap'}});
        }catch(e){unsupported.push({object_id:id,reason:String(e)});}
      }
      return {records,unsupported};
    },{ids:input.ids,count:input.count,svg:input.svg});
    process.stdout.write(JSON.stringify(result));
  }finally{await browser.close();}
})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;});
