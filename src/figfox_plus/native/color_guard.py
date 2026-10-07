"""Preserve visible first-draft outlines when a sample only supports the fill."""
from PIL import ImageColor

BOUNDARY_DISCOVERY = '''Compare structural boundaries before small S2 patches: inspect the original and current full figures for main panel outlines, compartment outlines, dashed enclosures and separator lines. Follow each source-visible side and corner in the current render, including portions behind replacement assets; a surviving label or one visible edge does not establish a complete outline. Check visibility, stroke color against the adjacent fill, dash pattern, opacity and CSS overrides. Name the compared boundaries in S2 whole_image_observation. A stroke attribute still present in XML is not evidence that its boundary remains visible in the render. Record an originally visible boundary that vanished or became indistinguishable from its background as S2. Preserve intentionally open or unframed regions in the original; do not invent enclosures.'''

BOUNDARY_REPAIR = '''For an existing structural boundary whose stroke or dash style disappeared, restore only the affected native frame/line properties with bp_patch, using independently located original-pixel color evidence (sample_colors where needed). Check both inline style and presentation attributes for overrides. Preserve child content and unrelated geometry; do not cover a large panel with a raster patch to restore its outline. Only omit an enclosure when original pixels support that omission.'''


class ColorSampleUnverified(ValueError):
    def __init__(self, check):
        self.check = check
        super().__init__('color sample would erase a visible outline; keep the first-draft colors')


def _rgb(node, attribute):
    styles = {k.strip(): v.strip() for item in node.get('style', '').split(';')
              if ':' in item for k, v in [item.split(':', 1)]}
    value = styles.get(attribute, node.get(attribute))
    if value is None:
        return None
    try:
        color = ImageColor.getrgb(value)
    except (ValueError, TypeError):
        return None
    return color if len(color) == 3 else None


def check_color_change(before, after, samples):
    """Local deferral only; contrast preservation is not visual acceptance."""
    if before.tag.rsplit('}', 1)[-1] not in ('rect', 'circle', 'ellipse', 'polygon'):
        return
    old_stroke, old_fill = _rgb(before, 'stroke'), _rgb(before, 'fill')
    new_stroke, new_fill = _rgb(after, 'stroke'), _rgb(after, 'fill')
    if any(color is None for color in (old_stroke, old_fill, new_stroke, new_fill)):
        return
    old_contrast = max(abs(a-b) for a, b in zip(old_stroke, old_fill))
    new_contrast = max(abs(a-b) for a, b in zip(new_stroke, new_fill))
    if old_contrast >= 24 and new_contrast <= 8:
        raise ColorSampleUnverified({'status': 'unverified', 'basis': 'first_draft_vs_sampled_style',
            'object_id': before.get('id'), 'before_stroke_rgb': old_stroke, 'before_fill_rgb': old_fill,
            'sampled_stroke_rgb': new_stroke, 'sampled_fill_rgb': new_fill,
            'before_contrast': old_contrast, 'sampled_contrast': new_contrast,
            'source_rois': samples, 'reason': 'sample supports the background, not a visible outline',
            'original_preserved': True, 'visual_acceptance': 'pending'})
