// Actual rendered alpha bounds, measured independently from layout/getBBox estimates.
const fs=require('fs');
const {chromium}=require(process.env.PLUS_PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
 const input=JSON.parse(fs.readFileSync(0,'utf8'));
 const browser=await chromium.launch({...(process.env.PLUS_CHROMIUM ? {executablePath:process.env.PLUS_CHROMIUM} : {}),headless:true});
 try {
  const context=await browser.newContext({viewport:{width:1800,height:1400}});
  await context.route('**/*',r=>r.abort());
  const page=await context.newPage();await page.setContent('<!doctype html><html><body style="margin:0">'+input.svg+'</body></html>');
  const result=await page.evaluate(async options=>{
   await document.fonts.ready;
   const root=document.querySelector('body>svg'), vb=root.viewBox.baseVal, rect=root.getBoundingClientRect();
   const canvas={x:vb.x,y:vb.y,width:vb.width||root.width.baseVal.value,height:vb.height||root.height.baseVal.value};
   const viewport={width:rect.width,height:rect.height};
   if(!viewport.width||!viewport.height)throw Error('empty SVG viewport');
   const rootCTM=root.getScreenCTM();
   if(Math.abs(rootCTM.b)>1e-9||Math.abs(rootCTM.c)>1e-9)throw Error('rotated/skewed root viewport unsupported; use an inner group');
   // Root world coordinates to this SVG element's CSS viewport. This includes
   // preserveAspectRatio alignment and letterboxing, unlike viewBox ratios.
   const world_to_viewport=[rootCTM.a,rootCTM.b,rootCTM.c,rootCTM.d,
                            rootCTM.e-rect.left,rootCTM.f-rect.top];
   const inv=rootCTM.inverse(), map=(x,y)=>new DOMPoint(x+rect.left,y+rect.top).matrixTransform(inv);
   if(options.layout){
    const drawable=new Set(['g','rect','circle','ellipse','polygon','polyline','path','line','text','image','use','svg']);
    const ids=options.ids||[...root.querySelectorAll('[id]')].filter(e=>drawable.has(e.localName)&&!e.closest('defs,marker,symbol,clipPath,mask')).map(e=>e.id);
    const objects={}, toWorld=(x,y)=>new DOMPoint(x,y).matrixTransform(inv);
    for(const id of ids){
     const el=root.querySelector('#'+CSS.escape(id));
     if(!el){objects[id]={status:'unsupported',reason:'unknown object ID',tight_bbox:null};continue;}
     if(el.closest('defs,marker,symbol,clipPath,mask')){objects[id]={status:'unsupported',reason:'definition is not an independently displayed object',tight_bbox:null};continue;}
     const r=el.getBoundingClientRect();
     if(!(r.width||r.height)){objects[id]={status:'empty',tight_bbox:null,reason:'no layout extent'};continue;}
     const p=toWorld(r.left,r.top), q=toWorld(r.right,r.bottom);
     objects[id]={status:'measured',tight_bbox:{left:Math.min(p.x,q.x),top:Math.min(p.y,q.y),right:Math.max(p.x,q.x),bottom:Math.max(p.y,q.y)},method:'layout-bbox'};
    }
    return {canvas,viewport,world_to_viewport,objects,contract:'Layout box of each object. Isolated alpha coverage is a separate measurement.'};
   }
   const scale=options.scale, pw=Math.ceil(viewport.width*scale), ph=Math.ceil(viewport.height*scale);
   if(pw*ph>options.max_pixels)throw Error('requested TP precision exceeds configured raster memory limit');
   const raster=document.createElement('canvas');raster.width=pw;raster.height=ph;
   const ctx=raster.getContext('2d',{willReadFrequently:true});
   // Freeze inherited/computed paint and text properties before removing siblings.
   const styled=root.cloneNode(true), originals=[root,...root.querySelectorAll('*')], clones=[styled,...styled.querySelectorAll('*')];
   const props=['display','visibility','opacity','fill','fill-opacity','fill-rule','stroke','stroke-width','stroke-opacity','stroke-linecap','stroke-linejoin','stroke-miterlimit','stroke-dasharray','stroke-dashoffset','paint-order','vector-effect','font-family','font-size','font-style','font-weight','font-stretch','font-kerning','font-variant','letter-spacing','word-spacing','text-anchor','dominant-baseline','alignment-baseline','writing-mode','text-orientation','white-space','color','filter','clip-path','mask','marker-start','marker-mid','marker-end','mix-blend-mode','transform','transform-origin','transform-box','x','y','width','height','cx','cy','r','rx','ry','d'];
   const resourceRoots=new Set([...root.querySelectorAll('defs,marker,symbol,clipPath,mask')]);
   for(const use of root.querySelectorAll('use')){const href=use.getAttribute('href')||use.getAttributeNS('http://www.w3.org/1999/xlink','href');if(href&&href.startsWith('#')){const ref=root.querySelector('#'+CSS.escape(href.slice(1)));if(ref)resourceRoots.add(ref);}}
   const inherited=new Set(['visibility','fill','fill-opacity','fill-rule','stroke','stroke-width','stroke-opacity','stroke-linecap','stroke-linejoin','stroke-miterlimit','stroke-dasharray','stroke-dashoffset','paint-order','font-family','font-size','font-style','font-weight','font-stretch','font-kerning','font-variant','letter-spacing','word-spacing','text-anchor','writing-mode','text-orientation','white-space','color','marker-start','marker-mid','marker-end']);
   function hasOwnDeclaration(el,k){
    if(el.hasAttribute(k)||el.style.getPropertyValue(k))return true;
    function matches(rules){for(const rule of rules){
     if(rule.selectorText){try{if(el.matches(rule.selectorText)&&rule.style.getPropertyValue(k))return true;}catch(_){}}
     else if(rule.cssRules&&(!rule.conditionText||!rule.media||matchMedia(rule.conditionText).matches)&&matches(rule.cssRules))return true;
    }return false;}
    return [...document.styleSheets].some(sheet=>{try{return matches(sheet.cssRules);}catch(_){return false;}});
   }
   for(let j=0;j<originals.length;j++){
    // A referenced source inherits unspecified paint from each use instance.
    // Lock the original cascade without accidentally freezing that inheritance.
    const resource=[...resourceRoots].some(r=>r===originals[j]||r.contains(originals[j]));
    const s=getComputedStyle(originals[j]);
    for(const k of props){let value=resource&&inherited.has(k)&&!hasOwnDeclaration(originals[j],k)?'inherit':s.getPropertyValue(k);if(value)clones[j].style.setProperty(k,value,'important');}
   }
   // Preserve the original viewport aspect mapping; DPR is applied by the canvas.
   styled.setAttribute('width',String(viewport.width));styled.setAttribute('height',String(viewport.height));
   styled.style.setProperty('width',viewport.width+'px','important');styled.style.setProperty('height',viewport.height+'px','important');
   const drawable=new Set(['g','rect','circle','ellipse','polygon','polyline','path','line','text','image','use','svg']);
   const ids=options.ids||[...root.querySelectorAll('[id]')].filter(e=>drawable.has(e.localName)&&!e.closest('defs,marker,symbol,clipPath,mask')).map(e=>e.id);
   const objects={};
   for(const id of ids){
    const el=root.querySelector('#'+CSS.escape(id));
    if(!el){objects[id]={status:'unsupported',reason:'unknown object ID',tight_bbox:null};continue;}
    if(el.closest('defs,marker,symbol,clipPath,mask')){objects[id]={status:'unsupported',reason:'definition is not an independently displayed object',tight_bbox:null};continue;}
    const effects=[];let ancestor=el;
    while(ancestor&&ancestor!==root.parentElement){const s=getComputedStyle(ancestor);if(s.mixBlendMode!=='normal')effects.push('background-dependent blend');ancestor=ancestor.parentElement;}
    for(const e of el.querySelectorAll('*'))if(getComputedStyle(e).mixBlendMode!=='normal')effects.push('descendant background-dependent blend');
    if(effects.length){objects[id]={status:'unsupported',reason:[...new Set(effects)].join(', '),tight_bbox:null};continue;}
    const isolated=styled.cloneNode(true), target=isolated.querySelector('#'+CSS.escape(id));
    // Give use instances private resource copies when their source is also
    // painted by this selection; direct paint and inherited instance paint differ.
    const privateResources=document.createElementNS('http://www.w3.org/2000/svg','defs');
    let privateIndex=0;
    for(const u of [...target.querySelectorAll('use')]){
     const href=u.getAttribute('href')||u.getAttributeNS('http://www.w3.org/1999/xlink','href');
     const source=href&&href.startsWith('#')?target.querySelector('#'+CSS.escape(href.slice(1))):null;
     if(!source||source.closest('defs,marker,symbol,clipPath,mask'))continue;
     const copy=source.cloneNode(true), aliases=new Map();
     for(const n of [copy,...copy.querySelectorAll('[id]')])if(n.id){let alias;do{alias='__tp_private_'+privateIndex++;}while(isolated.querySelector('#'+CSS.escape(alias)));aliases.set(n.id,alias);n.id=alias;}
     for(const n of [copy,...copy.querySelectorAll('*')])for(const attr of [...n.attributes]){
      let value=attr.value;
      if(attr.localName==='href'&&value.startsWith('#')&&aliases.has(value.slice(1)))value='#'+aliases.get(value.slice(1));
      value=value.replace(/url\(["']?#([^)'"\s]+)["']?\)/g,(m,ref)=>aliases.has(ref)?'url(#'+aliases.get(ref)+')':m);
      n.setAttributeNS(attr.namespaceURI,attr.name,value);
     }
     u.setAttribute('href','#'+copy.id);u.removeAttributeNS('http://www.w3.org/1999/xlink','href');privateResources.append(copy);
    }
    const sourceNodes=[el,...el.querySelectorAll('*')], targetNodes=[target,...target.querySelectorAll('*')];
    for(let j=0;j<sourceNodes.length;j++){
     if(sourceNodes[j].closest('defs,marker,symbol,clipPath,mask'))continue;
     const style=getComputedStyle(sourceNodes[j]);
     for(const k of props){const value=style.getPropertyValue(k);if(value)targetNodes[j].style.setProperty(k,value,'important');}
    }
    // Resources can be referenced outside <defs>; copy those to defs before pruning.
    const extra=document.createElementNS('http://www.w3.org/2000/svg','defs');let added=new Set();
    function dependencies(node,deep=true){
     for(const e of (deep?[node,...node.querySelectorAll('*')]:[node]))for(const a of e.attributes){
      const refs=[...a.value.matchAll(/url\(["']?#([^)'"\s]+)["']?\)/g)].map(m=>m[1]);
      if((a.localName==='href')&&a.value.startsWith('#'))refs.push(a.value.slice(1));
      for(const ref of refs){if(added.has(ref))continue;added.add(ref);const found=styled.querySelector('#'+CSS.escape(ref));
       if(found){if(!found.closest('defs')&&!target.contains(found)&&found!==target&&!found.contains(target)){extra.append(found.cloneNode(true));}dependencies(found);}
      }
     }
    }
    dependencies(target);
    for(let a=target.parentElement;a;a=a.parentElement){dependencies(a,false);if(a===isolated)break;}
    for(const resource of isolated.querySelectorAll('defs'))dependencies(resource);
    let branch=target;
    while(branch!==isolated){const parent=branch.parentElement;for(const child of [...parent.children])if(child!==branch&&!['defs','style','title','desc','metadata'].includes(child.localName))child.remove();branch=parent;}
    isolated.insertBefore(extra,isolated.firstChild);
    isolated.insertBefore(privateResources,isolated.firstChild);
    const text=new XMLSerializer().serializeToString(isolated);
    const blob=new Blob([text],{type:'image/svg+xml'}),url=URL.createObjectURL(blob),img=new Image();
    try {
     await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(Error('SVG image decode failed'));img.src=url;});
     ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,pw,ph);ctx.setTransform(scale,0,0,scale,0,0);ctx.drawImage(img,0,0,viewport.width,viewport.height);
     const rgba=ctx.getImageData(0,0,pw,ph).data;let left=pw,top=ph,right=-1,bottom=-1;
     for(let y=0;y<ph;y++){let row=y*pw*4;for(let x=0;x<pw;x++){if(rgba[row+x*4+3]>=options.alpha_threshold){left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=y;}}}
     if(right<0){objects[id]={status:'empty',tight_bbox:null,reason:'no visible coverage in document viewport'};continue;}
     const p=map(left/scale,top/scale),q=map((right+1)/scale,(bottom+1)/scale);
     const tight={left:Math.min(p.x,q.x),top:Math.min(p.y,q.y),right:Math.max(p.x,q.x),bottom:Math.max(p.y,q.y)};
     const box=el.getBBox(),m=root.getCTM().inverse().multiply(el.getCTM());
     objects[id]={status:'measured',tight_bbox:tight,local_geometry_bbox:{x:box.x,y:box.y,width:box.width,height:box.height},world:[m.a,m.b,m.c,m.d,m.e,m.f],
      touches_viewport:left===0||top===0||right===pw-1||bottom===ph-1,method:'isolated-render-alpha',alpha_threshold:options.alpha_threshold,sample_scale:scale,
      sampling_step:{x:Math.abs(inv.a)/scale,y:Math.abs(inv.d)/scale},includes_descendants:true,includes_ancestor_clipping:true,excludes_unrelated_occluders:true};
    }catch(e){objects[id]={status:'unsupported',reason:String(e),tight_bbox:null};}
    finally{URL.revokeObjectURL(url);}
   }
   return {canvas,viewport,world_to_viewport,objects,contract:'Minimum axis-aligned rectangle of isolated object rendered coverage, within document viewport. Precision limited by stated sample grid and 8-bit alpha threshold; not analytic infinite precision. Ancestor clipping and own descendants included; unrelated siblings/occluders excluded.'};
  },{ids:input.ids||null,scale:input.scale||4,alpha_threshold:input.alpha_threshold||1,max_pixels:input.max_pixels||40000000,layout:!!input.layout});
  process.stdout.write(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{process.stderr.write(String(e));process.exit(1)});
