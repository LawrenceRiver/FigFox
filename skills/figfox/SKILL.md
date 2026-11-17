---
name: figfox
description: Reconstruct a supplied scientific figure or generated diagram as editable SVG, preserving native text, geometry and connections, and repair confirmed local differences against the source. Use for raster-to-SVG reconstruction or source-matched SVG repair, not new figure ideation.
---

# FigFox

Turn the supplied figure into a standalone editable SVG through the **current calling assistant**. Use its vision, reasoning, file tools and a local renderer. No separate model API, provider credentials or SAM service is required for this skill. The repository's API runner is a separate execution mode; do not start it for a skill request.

Keep the original scientific content, layout, counts and directed relations. Reconstruct source errors faithfully unless the user asks to correct them. Photos and textures may remain independent source-derived image elements; labels, formulas, graph nodes, frames, charts and connectors stay native SVG. A PNG wrapped in `<image>`, or raster screenshots of whole text/diagram panels, is not editable reconstruction.

If the user supplies an existing SVG for editing, use it as the initial document and skip fresh reconstruction. Inspect its actual IDs, render a reference copy when needed, and perform only the requested edits plus their necessary checks. A source raster is needed only for raster comparison or source crops, not ordinary native text/group edits.

## Reconstruct, inspect, repair

1. **Read the source, then construct one complete draft.** Inspect the whole image and useful local regions. Establish the canvas and all aligned base frames first, with stable IDs. Within each frame, follow connected objects in order, preserving geometry, relative placement and arrow ownership. Use native `<text>`/`<tspan>` for labels and notation, and native shapes/paths/groups for diagrams. Derive colors from the source. Preserve photos as exact, separately movable crops with embedded image data. Finish every region before rendering; do not submit placeholder frames or unresolved crop/asset directives. See [reconstruction](references/reconstruction.md).
2. **Render and compare actual pixels.** Keep `initial.svg` and `initial.png`. Inspect source/draft whole images and paired close-ups, checking literal text, notation, counts, paths, arrowheads, overlaps and alignment. Record source and candidate observations separately; unreadable content remains uncertain. A source defect is not a reconstruction defect. The bundled `views` command makes four paired quadrants; request tighter views only for a specific unresolved observation. See [inspection](references/inspection-and-repair.md).
3. **Apply confirmed, scoped local repairs.** Bind observations to existing IDs using their containers, neighbors and relationships. Order dependent edits, preserve incident arrows, and list every issue as repaired or unresolved with reason. The bundled `apply` command validates target scope and executes the repository's native edit primitives locally. Re-render touched regions and neighbors. Avoid whole-image regeneration or unrelated redesign; stop when confirmed discrepancies are resolved or tools/evidence prevent further useful progress. Report remaining limitations rather than inventing content or declaring false success.
4. **Demonstrate editability and deliver.** In a separate copy, actually edit a label and a shape/group, and move an embedded photo if present; render the copy and verify the changes. Keep the deliverable unchanged by this probe. Deliver `final.svg`, `final.png`, source identity, object/asset inventory, observed issues and actual operation receipts. Report whether checks were by the same assistant or an independent reviewer. File validity, execution success, visual fidelity and practical editability are separate claims.

## Portable local tools

Resolve paths relative to this skill directory, not the repository or the user's current working directory. `scripts/` and `references/` travel with the installed skill. Use Python 3.10+ and Pillow from `requirements.txt`; rendering uses an available `rsvg-convert`, or CairoSVG as an optional fallback. These helpers perform no model or network calls. If a renderer is missing, use another available local SVG renderer; do not claim pixel inspection from XML validation alone.

If Pillow is missing, create a local environment with `python3 -m venv RUN/.venv`, then run `RUN/.venv/bin/python -m pip install -r SKILL_DIR/requirements.txt`, replacing `RUN` and `SKILL_DIR` with the actual output and installed skill directories. Use that environment's Python for the commands below.

```bash
python scripts/svg_tools.py inspect RUN/initial.svg
python scripts/svg_tools.py render RUN/initial.svg --out RUN/initial.png
python scripts/svg_tools.py views --source SOURCE.png --draft RUN/initial.png --out RUN/paired
python scripts/svg_tools.py apply RUN/initial.svg --plan RUN/repairs.json --source SOURCE.png --out RUN/final.svg
python scripts/svg_tools.py render RUN/final.svg --out RUN/final.png
```

`inspect` inventories native elements and flags image-only documents; it does not certify fidelity or editability. `apply` accepts the transaction schema in [native operations](references/native-operations.md), rejects writes outside declared target subtrees, preserves the input, and writes an execution receipt beside the output. Keep supporting files local unless publishing was requested. Do not install services, invoke paid providers, or publish just because the repository contains those capabilities.

FigFox-Gen generates a new raster figure from Methodology; **FigFox reconstructs an existing figure**. A generated figure can be passed here after the user chooses it. There is no automatic handoff or silent correction of generation errors.
