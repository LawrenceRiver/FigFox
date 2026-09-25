const fs=require('fs'),tracer=require('imagetracerjs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(tracer.imagedataToSVG(input.image,input.options));
