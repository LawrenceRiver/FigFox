"""Unmodified generic A-archive arrow-head geometry helpers (not quality metrics)."""
import math
import cv2
import numpy as np

def _angle_at(a, b, c):
    v1 = a - b
    v2 = c - b
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 180.0
    cos = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1, 1))
    return math.degrees(math.acos(cos))

def _foreground(bgr, mask=None):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 1] < 40) & (hsv[:, :, 2] > 205)
    fg = np.where(white, 0, 255).astype(np.uint8)
    if mask is not None:
        fg = cv2.bitwise_and(fg, mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel, iterations=1)

def heads_in_crop(bgr, mask=None, scale=4):
    h, w = bgr.shape[:2]
    if h < 1 or w < 1:
        return []
    work = cv2.resize(bgr, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)
    work_mask = None
    if mask is not None:
        work_mask = cv2.resize(mask, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)
    fg = _foreground(work, work_mask)
    contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = max(18, 0.012 * fg.shape[0] * fg.shape[1])
    heads = []
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        hull = cv2.convexHull(contour).reshape(-1, 2).astype(np.float64)
        if len(hull) < 3:
            continue
        peri = cv2.arcLength(hull.reshape(-1, 1, 2).astype(np.float32), True)
        approx = cv2.approxPolyDP(hull.reshape(-1, 1, 2).astype(np.float32), 0.06 * peri, True)
        pts = approx.reshape(-1, 2).astype(np.float64)
        if len(pts) < 3:
            pts = hull
        n = len(pts)
        sharp = []
        for i in range(n):
            ang = _angle_at(pts[(i - 1) % n], pts[i], pts[(i + 1) % n])
            if ang <= 72:
                sharp.append((ang, pts[i], pts[(i - 1) % n], pts[(i + 1) % n]))
        sharp.sort(key=lambda item: item[0])
        used = []
        for ang, tip, left, right in sharp[:2]:
            if any(np.linalg.norm(tip - other) < 4 for other in used):
                continue
            base = (left + right) / 2
            if np.linalg.norm(tip - base) < 3:
                continue
            used.append(tip)
            heads.append({
                'tip': (float(tip[0] / scale), float(tip[1] / scale)),
                'left': (float(left[0] / scale), float(left[1] / scale)),
                'right': (float(right[0] / scale), float(right[1] / scale)),
            })
    return heads

def _head_pixels(heads):
    if not heads:
        return None
    lengths = []
    widths = []
    for head in heads:
        tip = np.array(head['tip'], dtype=np.float64)
        left = np.array(head['left'], dtype=np.float64)
        right = np.array(head['right'], dtype=np.float64)
        base = (left + right) / 2
        lengths.append(float(np.linalg.norm(tip - base)))
        widths.append(float(np.linalg.norm(left - right)))
    length = max(1, int(round(float(np.median(lengths)))))
    width = max(1, int(round(float(np.median(widths)))))
    return length, width
