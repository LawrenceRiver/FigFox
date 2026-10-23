# Local runtime setup

Use a Python environment with the dependencies in `requirements.txt`, and install Node.js on `PATH`. From the repository root, install the pinned JavaScript packages and Chromium:

```sh
npm ci
npx playwright install chromium
```

The project pins Playwright to 1.62.1 in `package-lock.json`. The browser runners load the project's Playwright package by default and use the Chromium installed for that version. `npm ci` does not install the browser binary, so run the second command on each new machine or use an existing compatible executable.

The following environment variables select an existing runtime when needed:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PLUS_NODE` | `node` resolved on `PATH` | Explicit Node.js executable |
| `PLUS_PLAYWRIGHT_MODULE` | Project's `playwright` package | Explicit Playwright module path |
| `PLUS_CHROMIUM` | Browser installed for the project Playwright version | Explicit Chromium executable |
| `PLUS_VECTOR_PYTHON` | Current Python (`sys.executable`) | Python with a working `vtracer` installation |

For example, `PLUS_CHROMIUM=/absolute/path/to/chrome-headless-shell` uses an already installed browser without downloading another one. The overrides are passed to the browser processes as provided; the project does not insert a Codex cache or a user-specific path. The browser launch still blocks external requests as before.

For vector tracing, the observed `vtracer` 0.6.12 smoke crashed with exit `-11` under Python 3.14.6. The same small smoke succeeded with the existing Python 3.12.13 vector environment selected through `PLUS_VECTOR_PYTHON`. Use Python 3.12 for this path until the 3.14 compatibility issue is resolved. For example, after installing `requirements.txt` into a Python 3.12 environment:

```sh
export PLUS_VECTOR_PYTHON=/absolute/path/to/python3.12-environment/bin/python
```

The default current-Python setting is usable only when its installed `vtracer` actually works; installing the requirements alone does not establish that on Python 3.14.6.

Generated SVG construction code currently uses macOS `/usr/bin/sandbox-exec`. A macOS installation with that executable is the supported condition for that code execution path. The runtime reports `sandbox_unavailable` where this condition is absent.
