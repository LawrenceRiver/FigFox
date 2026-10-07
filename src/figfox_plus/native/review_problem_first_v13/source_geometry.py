"""Check source-pixel support before introducing cuboid depth.

This is a conservative execution guard, not a semantic classifier. An ambiguous
object stays unchanged; other programs remain executable. Raw replies are never
edited and passing edge checks does not grant visual acceptance.
"""
import hashlib
import io
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


DISCOVERY_POLICY = '''S1 applies only to cuboids visibly depicted in the ORIGINAL pixels. First distinguish planar rectangles, divided matrices/tensor columns and grids from solids with adjacent projected faces and shared depth edges. A tensor name, shading, or rectangular cells alone never proves 3D. Do not invent depth or a hidden face. If the original is planar, do not report its flat reconstruction as an S1 defect. If source dimensionality is unclear, mark uncertain. Once source 3D is established, compare missing faces, shared edges, segmentation, cell counts and stacking with the current render. Correct 3D objects with only placement errors belong to E/F. Preserve the original projection, including horizontal front edges when present, and only the faces actually shown; neither three visible faces nor a slanted front face is universal.'''

REPAIR_POLICY = '''Reinspect ORIGINAL pixels independently of the discovery claim before every S1 repair. You may correct a false S1 detection: return the same issue ID with decision:preserved and source_review:{classification:planar,evidence:what the original actually shows}, or decision:uncertain with source_review:{classification:uncertain,evidence:why depth cannot be established}. Retain the original description/evidence for audit and omit that repair. Do not invent coordinates to force a check to pass.
For a confirmed source cuboid, prefer route:module_program and sp_replace kind:geometry with data.shape:cuboid or lattice (divisions from the original). Other supported native operations and scoped generated_python remain available when the source projection needs them. Attach source_geometry:{basis:original_pixels,classification:cuboid,evidence:source object and visible adjacent faces,front_face:[[x,y],...four cyclic corners],adjacent_face:[[x,y],...four cyclic corners]} to each 3D SP operation, or to the program for another route. These are independently localized, unscaled ORIGINAL-image pixel coordinates, not current TP or proposed construction vertices. For a geometry cluster, source_geometry is an array with one proof per cuboid item, in item order. Do not invent coordinates to satisfy pixel thresholds. A missing or unsupported proof defers only that program, preserves the current object and records the unresolved reason; the default flow does not execute a separate candidate branch or open an extra model request. Keep unrelated repairs in independent programs so they can continue. Build geometry, colors and divisions from the actual original projection. Do not force slant, top faces or side faces absent from the original, and do not bypass explicit planar counterevidence. Source edge support and successful rendering still require semantic visual acceptance.'''


class SourceGeometryUnverified(ValueError):
    """A local mutation lacks source support; repeating it is not a recovery."""

    def __init__(self, reason, check=None):
        super().__init__('source geometry unverified: ' + reason)
        self.check = {'status': 'unverified', 'reason': reason,
                      'visual_acceptance': 'pending', **(check or {})}


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _face(value, size, label):
    if (not isinstance(value, list) or len(value) != 4
            or any(not isinstance(p, list) or len(p) != 2 for p in value)):
        raise SourceGeometryUnverified(label + ' needs four cyclic original-pixel corners')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for p in value for v in p):
        raise SourceGeometryUnverified(label + ' has non-finite coordinates')
    points = [tuple(p) for p in value]
    if any(not (0 <= x < size[0] and 0 <= y < size[1]) for x, y in points):
        raise SourceGeometryUnverified(label + ' lies outside the original image')
    turns = [_cross(_sub(points[(i+1) % 4], points[i]),
                    _sub(points[(i+2) % 4], points[(i+1) % 4])) for i in range(4)]
    if not (all(t > 2 for t in turns) or all(t < -2 for t in turns)):
        raise SourceGeometryUnverified(label + ' is flat, crossed or too small to verify')
    scale = max(math.dist(points[i], points[(i+1) % 4]) for i in range(4))
    if math.hypot(points[0][0]+points[2][0]-points[1][0]-points[3][0],
                  points[0][1]+points[2][1]-points[1][1]-points[3][1]) > max(2, scale*.04):
        raise SourceGeometryUnverified(label + ' does not establish a projected regular face')
    return points


def _source_edges(original):
    raw = Path(original).read_bytes()
    with Image.open(io.BytesIO(raw)) as image:
        rgba = image.convert('RGBA')
        rgb = Image.new('RGBA', rgba.size, 'white')
        rgb.alpha_composite(rgba)
        pixels = np.asarray(rgb.convert('RGB'))
    # Keep gradient direction: nearby horizontal borders must not stand in for
    # diagonal depth edges. Color gradients also cover unoutlined filled faces.
    gx = cv2.Sobel(pixels, cv2.CV_32F, 1, 0, ksize=3, scale=.25)
    gy = cv2.Sobel(pixels, cv2.CV_32F, 0, 1, ksize=3, scale=.25)
    channel = np.argmax(gx*gx + gy*gy, axis=2)[..., None]
    gx = np.take_along_axis(gx, channel, axis=2)[..., 0]
    gy = np.take_along_axis(gy, channel, axis=2)[..., 0]
    return (gx, gy), hashlib.sha256(raw).hexdigest()


def _edge_support(edges, start, end):
    length = math.dist(start, end)
    if length < 5:
        raise SourceGeometryUnverified('a visible edge is too short to distinguish from a corner')
    trim = min(.2, 3 / length)
    t = np.linspace(trim, 1-trim, max(5, math.ceil(length*2)))
    x = np.rint(start[0] + t * (end[0]-start[0])).astype(int)
    y = np.rint(start[1] + t * (end[1]-start[1])).astype(int)
    gx, gy = edges
    nx, ny = -(end[1]-start[1])/length, (end[0]-start[0])/length
    hits = np.zeros(len(t), dtype=bool)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            sx = np.clip(x+dx, 0, gx.shape[1]-1)
            sy = np.clip(y+dy, 0, gx.shape[0]-1)
            ax, ay = gx[sy, sx], gy[sy, sx]
            magnitude = ax*ax + ay*ay
            hits |= (magnitude >= 18**2) & ((ax*nx + ay*ny)**2 >= .9**2*magnitude)
    longest = run = 0
    for hit in hits:
        run = 0 if hit else run+1
        longest = max(longest, run)
    return {'supported_fraction': round(float(hits.mean()), 4),
            'longest_missing_fraction': round(longest/len(hits), 4)}


def _verify(proof, edges, source_hash):
    check = {'source_sha256': source_hash, 'visual_acceptance': 'pending',
             'edge_orientation_cosine_min': .9}
    if not isinstance(proof, dict) or proof.get('basis') != 'original_pixels':
        raise SourceGeometryUnverified('independent original-pixel face evidence is missing', check)
    if proof.get('classification') == 'planar':
        raise SourceGeometryUnverified('source proof explicitly identifies a planar object',
                                       {**check, 'candidate_allowed': False})
    if proof.get('classification') != 'cuboid':
        raise SourceGeometryUnverified('source is planar or its depth is uncertain', check)
    if not isinstance(proof.get('evidence'), str) or not proof['evidence'].strip():
        raise SourceGeometryUnverified('source object/face description is missing', check)
    size = (edges[0].shape[1], edges[0].shape[0])
    front = _face(proof.get('front_face'), size, 'front_face')
    adjacent = _face(proof.get('adjacent_face'), size, 'adjacent_face')
    shared = None
    for i in range(4):
        a, b = front[i], front[(i+1) % 4]
        for j in range(4):
            if math.dist(a, adjacent[j]) <= 1.5 and math.dist(b, adjacent[(j+1) % 4]) <= 1.5:
                shared = (i, adjacent[(j-1) % 4], adjacent[(j+2) % 4])
            elif math.dist(b, adjacent[j]) <= 1.5 and math.dist(a, adjacent[(j+1) % 4]) <= 1.5:
                shared = (i, adjacent[(j+2) % 4], adjacent[(j-1) % 4])
    if shared is None:
        raise SourceGeometryUnverified('source faces do not share an edge', check)
    i, far_a, far_b = shared
    a, b = front[i], front[(i+1) % 4]
    depth_a, depth_b = _sub(far_a, a), _sub(far_b, b)
    if math.dist(depth_a, depth_b) > max(2, math.hypot(*depth_a)*.04):
        raise SourceGeometryUnverified('source depth edges are inconsistent', check)
    # Adjacent grid cells lie along a front-face axis and cannot prove depth.
    axes = (_sub(front[1], front[0]), _sub(front[3], front[0]))
    length = math.hypot(*depth_a)
    if length < 5 or any(abs(_cross(axis, depth_a)) <= .15*math.hypot(*axis)*length for axis in axes):
        raise SourceGeometryUnverified('source depth is indistinguishable from planar divisions', check)
    interior = _sub(front[(i+2) % 4], a)
    if _cross(_sub(b, a), interior) * _cross(_sub(b, a), depth_a) >= 0:
        raise SourceGeometryUnverified('adjacent source face overlaps the front face', check)
    segments = [(front[k], front[(k+1) % 4]) for k in range(4)]
    segments.extend(((a, far_a), (b, far_b), (far_a, far_b)))
    supports = [_edge_support(edges, s, e) for s, e in segments]
    check.update(front_face=proof['front_face'], adjacent_face=proof['adjacent_face'],
                 edge_support=supports)
    if any(s['supported_fraction'] < .7 or s['longest_missing_fraction'] > .35 for s in supports):
        raise SourceGeometryUnverified('claimed face/depth edges lack original-pixel support in their declared directions', check)
    return {'status': 'edges_supported', **check}


def check_source_geometry(program, original, *, require_source=False):
    """Check each 3D SP replacement, including nested operations and clusters."""
    def replacements(operations):
        for op in operations or []:
            if not isinstance(op, dict):
                continue
            args = op.get('args') if isinstance(op.get('args'), dict) else {}
            if op.get('method') == 'bp_program':
                yield from replacements(args.get('operations'))
            data = args.get('data')
            if (op.get('method') == 'sp_replace' and args.get('kind') == 'geometry'
                    and isinstance(data, dict) and data.get('shape') in ('cuboid', 'lattice', 'cluster')):
                if data['shape'] != 'cluster' or any(item.get('shape') == 'cuboid'
                                                    for item in data.get('items', []) if isinstance(item, dict)):
                    yield op
    ops = (list(replacements(program.get('args', {}).get('operations')))
           if program.get('route') == 'module_program' else [])
    if not ops and not require_source:
        return []
    edges, source_hash = _source_edges(original)
    reports = []
    if not ops:
        proof = program.get('source_geometry')
        proofs = proof if isinstance(proof, list) else [proof]
        if not proofs:
            raise SourceGeometryUnverified('independent original-pixel face evidence is missing')
        return [{**_verify(item, edges, source_hash), 'target_ids': program.get('target_ids', [])}
                for item in proofs]
    for op in ops:
        data = op['args']['data']
        proof = op.get('source_geometry')
        if data['shape'] == 'cluster':
            items = data.get('items', [])
            if not isinstance(proof, list) or len(proof) != len(items):
                raise SourceGeometryUnverified('each cluster item needs its own original-pixel proof')
            proofs = [p for item, p in zip(items, proof) if item.get('shape') == 'cuboid']
        else:
            proofs = [proof]
        for item_proof in proofs:
            reports.append({**_verify(item_proof, edges, source_hash), 'target_ids': op.get('target_ids', [])})
    return reports
