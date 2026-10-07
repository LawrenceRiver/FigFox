"""Run identity and atomic evidence records; no API side effects."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
from uuid import uuid4

PLUS_ROOT = Path(__file__).resolve().parents[2]


def new_run(root: Path, stage: str) -> Path:
    if not re.fullmatch(r'[a-z][a-z0-9-]*', stage):
        raise ValueError('invalid stage name')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    path = root / f'{stage}-{now}-{uuid4().hex[:10]}'
    path.mkdir(exist_ok=False)
    return path


def replace_file(source, target) -> None:
    """Keep atomic writes through brief Windows reader/antivirus sharing locks."""
    for attempt in range(6):
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 5:
                raise
            time.sleep(0.01 * 2**attempt)


def write_json(path: Path, data) -> None:
    path = Path(path)
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    # Packaged Windows apps can redirect AppData to another drive. Resolve both
    # paths before atomic replacement so the temporary file shares its volume.
    path = path.resolve()
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        replace_file(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
