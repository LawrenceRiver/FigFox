"""Open only a registered notification's status page or PNG; never execute commands."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from figfox_plus.notifications import resolve_action

if __name__ == '__main__':
    path = resolve_action(sys.argv[1]) if len(sys.argv)==2 else ROOT/'runs' if len(sys.argv)==1 else None
    if path is None:
        raise SystemExit('invalid notification action')
    os.startfile(path)
