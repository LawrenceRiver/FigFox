const fs=require('fs');
const {mathjax}=require('mathjax-full/js/mathjax.js');
const {TeX}=require('mathjax-full/js/input/tex.js');
const {SVG}=require('mathjax-full/js/output/svg.js');
const {liteAdaptor}=require('mathjax-full/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler}=require('mathjax-full/js/handlers/html.js');
require('mathjax-full/js/input/tex/AllPackages.js');
const adaptor=liteAdaptor(); RegisterHTMLHandler(adaptor);
try {
 const input=JSON.parse(fs.readFileSync(0,'utf8'));
 if(typeof input.tex!=='string' || !input.tex.trim()) throw Error('Formula requires nonempty LaTeX');
 const tex=new TeX({packages:['base','ams','newcommand'],formatError:(_jax,error)=>{throw error;}});
 const doc=mathjax.document('',{InputJax:tex,OutputJax:new SVG({fontCache:'none'})});
 const node=doc.convert(input.tex,{display:true});
 const svg=adaptor.firstChild(node);
 const box=(adaptor.getAttribute(svg,'viewBox')||'').trim().split(/\s+/).map(Number);
 if(box.length!==4 || !box.every(Number.isFinite) || box[2]<=0 || box[3]<=0) throw Error('Invalid formula glyph viewBox');
 process.stdout.write(adaptor.outerHTML(node));
} catch(e) { process.stderr.write(String(e));process.exit(1); }
