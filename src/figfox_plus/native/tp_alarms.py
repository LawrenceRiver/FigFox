"""Offline, current-image TP relation alarms. Never a visual acceptance or repair."""
import math


def _number(value, name, *, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def evaluate_tp(objects, relations, *, revision, epsilon=1e-6,
                coordinate_space="current_svg_world"):
    """Check explicit source-justified relations on measured current-world boxes.

    Separate: signed axis gap must be >= min_gap (default zero).
    Contain: subject box must be inside object box, inset by padding.
    Legal overlap: explicitly preserve an original-image relation.
    Every violated relation is indexed under both participants. Incomplete
    boundaries remain uncertain; satisfied constraints never prove visual quality.
    """
    _number(epsilon, "epsilon", nonnegative=True)
    if coordinate_space != "current_svg_world":
        raise ValueError("TP alarms only accept current SVG world coordinates")
    if not isinstance(revision, str) or not revision:
        raise ValueError("revision is required")
    boxes = {}
    for oid, item in objects.items():
        if not isinstance(oid, str) or not oid or item.get("revision") != revision:
            raise ValueError("invalid object ID or stale measurement")
        if not isinstance(item.get("bounds_complete"), bool):
            raise ValueError("bounds_complete must be explicit")
        bbox = item["bbox"]
        b = {k: _number(bbox[k], k) for k in ("left", "top", "right", "bottom")}
        if b["right"] <= b["left"] or b["bottom"] <= b["top"]:
            raise ValueError("TP box must have positive width and height")
        boxes[oid] = b
    checks, alarms, by_object, seen = [], [], {}, set()
    for rule in relations:
        rid = rule["id"]
        if not isinstance(rid, str) or not rid or rid in seen:
            raise ValueError("relation IDs must be nonempty and unique")
        seen.add(rid)
        a, b = rule["subject_id"], rule["object_id"]
        if a == b or a not in boxes or b not in boxes:
            raise ValueError("relation needs two distinct measured participants")
        predicate = rule["predicate"]
        if predicate not in {"separate", "contain", "legal_overlap"}:
            raise ValueError("unsupported relation predicate")
        evidence = rule.get("reference_evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("original semantic relation evidence is required")
        min_gap = _number(rule.get("min_gap", 0), "min_gap", nonnegative=True)
        padding = _number(rule.get("padding", 0), "padding", nonnegative=True)
        x, y = boxes[a], boxes[b]
        measurement = {}
        if predicate == "separate":
            signed_gap = max(y["left"]-x["right"], x["left"]-y["right"],
                             y["top"]-x["bottom"], x["top"]-y["bottom"])
            measurement = {"signed_axis_gap": signed_gap}
            passed = signed_gap >= min_gap-epsilon
        elif predicate == "contain":
            margins = [x["left"]-y["left"], x["top"]-y["top"],
                       y["right"]-x["right"], y["bottom"]-x["bottom"]]
            measurement = {"margins_ltrb": margins}
            passed = min(margins) >= padding-epsilon
        else:
            passed = True
        complete = objects[a]["bounds_complete"] and objects[b]["bounds_complete"]
        status = "uncertain" if not complete else ("satisfied" if passed else "violated")
        result = {"id": rid, "participants": [a,b], "predicate": predicate,
                  "min_gap": min_gap, "padding": padding,
                  "reference_evidence": evidence, "status": status,
                  "measurement": measurement, "basis": "current_measured_aabb",
                  "visual_passed": False}
        checks.append(result)
        if status == "violated":
            alarms.append(result)
            for oid in (a,b):
                by_object.setdefault(oid, []).append(rid)
    return {"revision": revision, "coordinate_space": coordinate_space,
            "relations": checks, "alarms": alarms,
            "by_object": by_object,
            "uncertain_ids": [r["id"] for r in checks if r["status"] == "uncertain"],
            "hard_constraints_passed": bool(checks) and all(r["status"] == "satisfied" for r in checks),
            "visual_passed": False}


def compare_reports(before, after):
    """Report regressions without silently dropping or changing neighbour checks."""
    old = {r["id"]: r for r in before["relations"]}
    new = {r["id"]: r for r in after["relations"]}
    old_bad = {i for i,r in old.items() if r["status"] == "violated"}
    new_bad = {i for i,r in new.items() if r["status"] == "violated"}
    missing = set(old)-set(new)
    keys = ("participants", "predicate", "min_gap", "padding", "reference_evidence")
    changed = {i for i in set(old)&set(new) if any(old[i][k] != new[i][k] for k in keys)}
    uncertain = {i for i,r in new.items() if r["status"] == "uncertain"}
    cleared = {i for i in old_bad & set(new) if new[i]["status"] == "satisfied" and i not in changed}
    return {"new_alarm_ids": sorted(new_bad-old_bad),
            "cleared_alarm_ids": sorted(cleared), "remaining_alarm_ids": sorted(new_bad),
            "missing_relation_ids": sorted(missing), "changed_relation_ids": sorted(changed),
            "uncertain_ids": sorted(uncertain),
            "no_new_neighbor_alarms": bool(new) and not (new_bad-old_bad or missing or changed or uncertain),
            "visual_passed": False}
