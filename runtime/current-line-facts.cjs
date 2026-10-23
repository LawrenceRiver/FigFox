// Offline current SVG facts: no original coordinates and no defect decisions.
const fs = require('fs');
const {chromium} = require(process.env.PLUS_PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({...(process.env.PLUS_CHROMIUM ? {executablePath:process.env.PLUS_CHROMIUM} : {}), headless: true});
  try {
    const context = await browser.newContext({javaScriptEnabled: false, serviceWorkers: 'block', viewport: {width: 1200, height: 1000}});
    await context.route('**/*', route => route.abort());
    const page = await context.newPage();
    await page.setContent('<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:"></head><body>'+input.svg+'</body></html>');
    const result = await page.evaluate(() => {
      const root = document.querySelector('body > svg');
      if (!root || !root.getCTM()) throw Error('SVG root CTM unavailable');
      const inverse = root.getCTM().inverse();
      const vb = root.viewBox.baseVal;
      const scale = Math.max(Math.hypot(vb.width || root.width.baseVal.value, vb.height || root.height.baseVal.value), 1);
      const tolerance = scale * 1e-6;
      const angularTolerance = 1e-5;
      const report = {domain:'current_svg_only', coordinate_space:'current_svg_world', diagnosis_confirmed:false,
        objects:[], relation_candidates:[], unsupported:[], thresholds:{distance:tolerance, angle_radians:angularTolerance},
        instruction:'Geometry and relations are candidates, not errors. Original-image VLM must confirm or refute intended connections and alignment. Never transfer current coordinates onto the original image.',
        limitations:['Sampled geometry is approximate and cannot certify arbitrary small loops or features.', 'Path endpoints are not marker tips. Tangents are numerical approximations; orientation follows path order, not semantic arrow direction.', 'Invisible centerlines may be measured; visibility/paint effects require rendered review. Current proximity, equal lengths or parallelism do not establish semantic relations or required symmetry.', 'Clipping, masking, occlusion, dash patterns and marker paint are not included in centerline geometry.', 'Use instances, raster arrows, compound paths and closed contours require additional visual/structural inspection.', 'Animation and active/foreign content are excluded; external resources are blocked.']};
      const all = [...root.querySelectorAll('*')];
      const idCounts = new Map();
      for (const e of all) if(e.id) idCounts.set(e.id,(idCounts.get(e.id)||0)+1);
      const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
      const unit=v=>{const n=Math.hypot(...v);return n>0?v.map(x=>x/n):null;};
      const minus=(a,b)=>[a[0]-b[0],a[1]-b[1]];
      const cross=(a,b)=>a[0]*b[1]-a[1]*b[0];
      const dot=(a,b)=>a[0]*b[0]+a[1]*b[1];
      function marker(value) {
        if (!value || value==='none') return null;
        const match=value.match(/url\(["']?([^"')]+)["']?\)/);
        const ref=match?match[1]:null;
        const id=ref&&ref.startsWith('#')?ref.slice(1):null;
        const e=id?document.getElementById(id):null;
        return {computed_reference:value, marker_id:id, resolved:!!e&&e.localName==='marker'&&idCounts.get(id)===1,
          attributes:e?Object.fromEntries([...e.attributes].map(a=>[a.name,a.value])):null,
          content:e?e.innerHTML:null, tip_inferred:false};
      }
      function pathInfo(d) {
        const token=/[a-df-zA-DF-Z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?/g;
        const tokens=d.match(token)||[];
        if(d.replace(token,'').replace(/[\s,]/g,''))return 'invalid_path_syntax';
        const arity={M:2,L:2,H:1,V:1,C:6,S:4,Q:4,T:2,A:7,Z:0};
        let i=0,moves=0,closed=false;
        while(i<tokens.length){
          const cmd=tokens[i++].toUpperCase();
          if(!(cmd in arity)||(i===1&&cmd!=='M'))return 'invalid_path_syntax';
          if(cmd==='M')moves++;
          if(cmd==='Z'){closed=true;continue;}
          const start=i;
          while(i<tokens.length&&!/^[a-z]$/i.test(tokens[i]))i++;
          if(i===start||(i-start)%arity[cmd])return 'invalid_path_syntax';
          if(tokens.slice(start,i).some(x=>!Number.isFinite(Number(x))))return 'invalid_path_syntax';
          if(cmd==='A')for(let k=start;k<i;k+=7)if(!['0','1'].includes(tokens[k+3])||!['0','1'].includes(tokens[k+4]))return 'unsupported_arc_flag_syntax';
        }
        return moves>1?'multiple_subpaths':closed?'closed_contour':moves===0?'empty_path':null;
      }
      for (let index=0;index<all.length;index++) {
        const e=all[index],tag=e.localName;
        if(!['line','polyline','path','polygon','use','image'].includes(tag))continue;
        const id=e.id||'@node:'+index;
        const o={object_id:id,tag,measurement_status:'unresolved',markers:{},world_start:null,world_end:null};
        report.objects.push(o);
        const unsupported=reason=>{o.reason=reason;report.unsupported.push({object_id:id,reason});};
        if(e.closest('defs,marker,symbol,clipPath,mask,pattern')){unsupported('definition_only');continue;}
        if(e.id&&idCounts.get(e.id)>1){unsupported('duplicate_id');continue;}
        if(tag==='use'||tag==='image'){unsupported(tag==='use'?'use_instance_topology_unresolved':'raster_topology_unresolved');continue;}
        if(tag==='polygon'){unsupported('closed_contour');continue;}
        if(tag==='polyline'&&e.points.numberOfItems>1){
          const first=e.points.getItem(0),last=e.points.getItem(e.points.numberOfItems-1);
          if(first.x===last.x&&first.y===last.y){unsupported('closed_contour');continue;}
        }
        const style=getComputedStyle(e);
        o.markers={start:marker(style.markerStart),mid:marker(style.markerMid),end:marker(style.markerEnd)};
        o.style={stroke:style.stroke,stroke_width:style.strokeWidth,fill:style.fill,display:style.display,visibility:style.visibility,opacity:style.opacity};
        o.arrow_semantics_confirmed=false;
        if(tag==='path'){
          const computed=style.getPropertyValue('d');
          const match=computed&&computed.match(/^path\(["']([\s\S]*)["']\)$/);
          const d=match?match[1]:e.getAttribute('d')||'';
          o.path_data=d;
          const reason=pathInfo(d);if(reason){unsupported(reason);continue;}
        }
        try {
          const localLength=e.getTotalLength();
          if(!Number.isFinite(localLength)||localLength<=0){unsupported('zero_or_invalid_length');continue;}
          const ctm=e.getCTM();if(!ctm){unsupported('missing_ctm');continue;}
          const m=inverse.multiply(ctm);
          if(![m.a,m.b,m.c,m.d,m.e,m.f].every(Number.isFinite)||Math.abs(m.a*m.d-m.b*m.c)<1e-14){unsupported('singular_or_invalid_transform');continue;}
          o.world_matrix=[m.a,m.b,m.c,m.d,m.e,m.f];
          const point=t=>{const p=e.getPointAtLength(t),q=new DOMPoint(p.x,p.y).matrixTransform(m);return [q.x,q.y];};
          // Dyadic refinement in world space handles nonuniform scales and curves.
          let points=[],length=0,previous=-1,converged=false,n;
          for(n=32;n<=2048;n*=2){
            points=Array.from({length:n+1},(_,i)=>point(localLength*i/n));
            length=points.slice(1).reduce((s,p,i)=>s+distance(points[i],p),0);
            if(previous>=0&&Math.abs(length-previous)<=tolerance){converged=true;break;}
            previous=length;
          }
          const start=points[0],end=points[points.length-1],chord=distance(start,end),direction=unit(minus(end,start));
          const residual=direction?Math.max(...points.map(p=>Math.abs(cross(minus(p,start),direction)))):length;
          o.measurement_status='measured';
          Object.assign(o,{world_start:start,world_end:end,start_tangent:unit(minus(point(Math.min(localLength,localLength*1e-5)),start)),end_tangent:unit(minus(end,point(localLength*(1-1e-5)))),chord_length:chord,world_arc_length:length,direction,straightness_residual:residual,straightness_qualified:!!direction&&residual<=tolerance&&length-chord<=tolerance,sample_count:points.length,length_converged:converged,length_tolerance:tolerance});
        } catch(err){unsupported('browser_geometry_unavailable: '+String(err));}
      }
      const lines=report.objects.filter(o=>o.measurement_status==='measured'&&o.straightness_qualified);
      for(let i=0;i<lines.length;i++)for(let j=i+1;j<lines.length;j++){
        const a=lines[i],b=lines[j],angle=Math.atan2(Math.abs(cross(a.direction,b.direction)),Math.abs(dot(a.direction,b.direction)));
        const parallel=angle<=angularTolerance;
        const perpendicular=Math.max(Math.abs(cross(minus(b.world_start,a.world_start),a.direction)),Math.abs(cross(minus(b.world_end,a.world_start),a.direction)));
        const projection=[dot(minus(b.world_start,a.world_start),a.direction),dot(minus(b.world_end,a.world_start),a.direction)].sort((a,b)=>a-b);
        report.relation_candidates.push({object_ids:[a.object_id,b.object_id],kind:'straight_line_pair',parallel,angle_radians:angle,same_path_direction:dot(a.direction,b.direction)>=0,perpendicular_distance:perpendicular,coaxial:parallel&&perpendicular<=tolerance,projected_intervals:[[0,a.chord_length],projection],length_difference:b.world_arc_length-a.world_arc_length,length_ratio:b.world_arc_length/a.world_arc_length,endpoint_distances:{start_start:distance(a.world_start,b.world_start),start_end:distance(a.world_start,b.world_end),end_start:distance(a.world_end,b.world_start),end_end:distance(a.world_end,b.world_end)},requires_original_visual_confirmation:true});
      }
      // Group by computed presentation and directed geometry only, never IDs/names.
      const buckets=[];
      const styleKey=o=>JSON.stringify([o.style.stroke,o.style.stroke_width,
        o.markers.start?.computed_reference||null,o.markers.end?.computed_reference||null]);
      for(const line of lines){
        const key=styleKey(line);
        // Complete-link check avoids angle tolerance chaining across a wide fan.
        let group=buckets.find(g=>g.key===key&&g.lines.every(other=>
          dot(other.direction,line.direction)>0&&
          Math.atan2(Math.abs(cross(other.direction,line.direction)),dot(other.direction,line.direction))<=angularTolerance));
        if(!group){group={key,lines:[]};buckets.push(group);}
        group.lines.push(line);
      }
      report.parallel_groups=buckets.filter(g=>g.lines.length>=2).map(group=>{
        const axis=unit(group.lines.reduce((v,o)=>[v[0]+o.direction[0],v[1]+o.direction[1]],[0,0]));
        const perpendicular=[-axis[1],axis[0]];
        const members=group.lines.map(o=>({object_id:o.object_id,world_start:o.world_start,world_end:o.world_end,
          world_arc_length:o.world_arc_length,chord_length:o.chord_length,
          perpendicular_position:dot([(o.world_start[0]+o.world_end[0])/2,(o.world_start[1]+o.world_end[1])/2],perpendicular),
          start_projection:dot(o.world_start,axis),end_projection:dot(o.world_end,axis)}))
          .sort((a,b)=>a.perpendicular_position-b.perpendicular_position||a.start_projection-b.start_projection);
        const span=key=>Math.max(...members.map(m=>m[key]))-Math.min(...members.map(m=>m[key]));
        const mirrors=[];
        for(let i=0;i<Math.floor(members.length/2);i++){
          const a=members[i],b=members[members.length-1-i];
          mirrors.push({object_ids:[a.object_id,b.object_id],sorted_indices:[i,members.length-1-i],
            length_difference:b.world_arc_length-a.world_arc_length,
            basis:'sorted outer-to-inner pairing only; does not establish intended symmetry',requires_original_visual_confirmation:true});
        }
        return {style:{stroke:group.lines[0].style.stroke,stroke_width:group.lines[0].style.stroke_width,
          marker_start_reference:group.lines[0].markers.start?.computed_reference||null,
          marker_end_reference:group.lines[0].markers.end?.computed_reference||null},
          direction:axis,perpendicular_direction:perpendicular,members,
          start_projection_span:span('start_projection'),end_projection_span:span('end_projection'),
          common_start_line_candidate:span('start_projection')<=tolerance,
          common_end_line_candidate:span('end_projection')<=tolerance,
          mirror_length_candidates:mirrors,intended_symmetry_confirmed:false,
          instruction:'All members share presentation and directed parallel geometry; this is not a semantic group or an error verdict. Original-image visual confirmation is required.'};
      });
      report.coverage={object_count:report.objects.length,measured_count:report.objects.filter(o=>o.measurement_status==='measured').length,straight_count:lines.length,pairs_examined:lines.length*(lines.length-1)/2,candidate_limit:null};
      return report;
    });
    process.stdout.write(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(e=>{process.stderr.write(String(e));process.exit(1);});
