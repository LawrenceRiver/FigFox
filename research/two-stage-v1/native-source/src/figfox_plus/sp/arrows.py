"""Deterministic arrow routes. Coordinates refer to actual arrow tips."""
from math import hypot, isfinite


def route_path(points, route='polyline', radius=8):
    pts=[tuple(map(float,p)) for p in points]
    if len(pts)<2 or any(len(p)!=2 or not all(map(isfinite,p)) for p in pts):
        raise ValueError('arrow requires finite two-dimensional points')
    if any(a==b for a,b in zip(pts,pts[1:])):
        raise ValueError('arrow has zero-length segment')
    if not isfinite(radius) or radius<0:
        raise ValueError('arrow radius must be finite and nonnegative')
    def pair(p): return f'{p[0]:g} {p[1]:g}'
    result='M '+pair(pts[0])
    if route=='cubic':
        if len(pts)!=4: raise ValueError('cubic arrow requires four points')
        return result+' C '+' '.join(map(pair,pts[1:]))
    if route=='line' and len(pts)!=2:
        raise ValueError('line arrow requires two points')
    if route not in ('line','polyline','rounded'):
        raise ValueError('unsupported arrow route')
    if route!='rounded': return result+' L '+' L '.join(map(pair,pts[1:]))
    for a,b,c in zip(pts,pts[1:],pts[2:]):
        incoming=hypot(b[0]-a[0],b[1]-a[1]);outgoing=hypot(c[0]-b[0],c[1]-b[1])
        cut=min(radius,incoming/2,outgoing/2)
        entry=tuple(b[i]+(a[i]-b[i])*cut/incoming for i in range(2))
        leave=tuple(b[i]+(c[i]-b[i])*cut/outgoing for i in range(2))
        result+=' L '+pair(entry)+' Q '+pair(b)+' '+pair(leave)
    return result+' L '+pair(pts[-1])


def head_triangle(tip, adjacent, length, width):
    """Triangle behind the tip, using the final route tangent."""
    if not all(isfinite(v) and v>0 for v in (length,width)):
        raise ValueError('arrow head dimensions must be positive and finite')
    dx,dy=tip[0]-adjacent[0],tip[1]-adjacent[1]
    norm=hypot(dx,dy)
    if not norm: raise ValueError('arrow tangent is zero')
    ux,uy=dx/norm,dy/norm
    base=(tip[0]-length*ux,tip[1]-length*uy)
    return [list(tip),[base[0]-uy*width/2,base[1]+ux*width/2],
            [base[0]+uy*width/2,base[1]-ux*width/2]]
