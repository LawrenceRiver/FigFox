"""Zero-network byte verification for the published actual source snapshot."""
import pathlib,json,hashlib
root=pathlib.Path(__file__).resolve().parent
manifest=json.loads((root/'snapshot-sha256.json').read_text())
for name,digest in manifest['files'].items():
 p=root/name
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise SystemExit('source mismatch: '+name)
print('Verified',len(manifest['files']),'published source files; no API requests.')
