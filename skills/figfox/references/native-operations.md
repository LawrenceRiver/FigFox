# Portable native edit interface

The installed skill includes `scripts/native_edits.py`, a source copy of `src/figfox_plus/factual/contracts.py`. `scripts/svg_tools.py` uses its scope validation, safe-SVG checks and edit executor without importing the repository or calling providers. Keep the bundled copy synchronized when changing the upstream contracts. The skill supports six native operation names; TP operations and provider/runtime services are outside this portable interface.

```json
{
  "transactions": [
    {
      "id": "fix-caption",
      "target_ids": ["caption-group"],
      "depends_on": [],
      "operations": [
        {"op": "text", "id": "caption", "text": "Correct source literal"}
      ]
    }
  ]
}
```

Each transaction requires `id`, `target_ids`, `depends_on` and `operations`. Always write `depends_on: []` for an independent transaction. Targets must exist in the input SVG; a group permits its subtree. Dependencies precede the transaction. IDs and values above are illustrative—derive the actual ones from the current image and SVG. `ROOT` is useful only for an explicitly justified append context, not a way to evade local targeting.

- `set`: `{op, id, attributes}` changes existing attributes.
- `text`: `{op, id, text}` changes existing text; existing child tspans remain. Use `replace_svg` for a new formula/tspan structure.
- `remove`: `{op, id}` removes that node and descendants.
- `append_svg`: `{op, parent_id, svg}` appends one well-formed native SVG element.
- `replace_svg`: `{op, id, svg}` replaces one element in place, not the canvas/background.
- `source_crop`: `{op, parent_id, id, source_box:[left,top,right,bottom], target_box:[x,y,width,height], remove_ids:[]}` embeds a local source crop. It requires `--source`. No crop may cover 30% or more of the canvas; cumulative crop area is below 50%. These mechanical limits do not authorize rasterizing scientific text or diagram panels.

Move a group with `set` on its `transform` attribute; this uses the same `set` schema.

SVG fragments carry `xmlns="http://www.w3.org/2000/svg"`. IDs must be unique, resource references must resolve, and scripts, event handlers, foreignObject and external resources are rejected. After a parent replacement, its removed descendants are no longer valid targets. The input SVG is preserved; use a new output filename. The execution receipt records actual operations, input/output hashes and `visual_quality_pass: null`.
