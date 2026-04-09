"""
ADIE — Auto-generated Validation Script
Rule ID  : R005
Rule     : max_aspect_ratio
Value    : 10.0 (dimensionless ratio)
Condition: (all solid bodies)
Severity : warning
Source   : page 18

CONTRACT:
    validate_R005(design) -> dict

METHOD:
    Computes the bounding-box aspect ratio for each solid body using
    physicalProperties bounding box dimensions (or edge scanning fallback).
    Aspect ratio = longest_axis / shortest_axis.
    High ratios indicate very slender parts that may be fragile or hard to
    fixture for machining.

    Fusion geometry: cm.  Ratio is dimensionless so no conversion needed.
"""

_REQUIRED_MAX_RATIO = 10.0
_UNIT               = "ratio"


def _compute_bounding_box_dims(body):
    """
    Return (dx, dy, dz) bounding box dimensions in cm using Bounding box
    from physicalProperties, falling back to edge-scan extremes.
    """
    # Attempt 1: physicalProperties bounding box
    try:
        bb = body.physicalProperties.boundingBox
        if bb is not None:
            mn = bb.minPoint
            mx = bb.maxPoint
            dx = abs(mx.x - mn.x)
            dy = abs(mx.y - mn.y)
            dz = abs(mx.z - mn.z)
            if dx > 0 and dy > 0 and dz > 0:
                return dx, dy, dz
    except Exception:
        pass

    # Attempt 2: scan edge vertices for bounding box (slower fallback)
    xs, ys, zs = [], [], []
    try:
        for ei in range(body.edges.count):
            edge = body.edges.item(ei)
            for vi in range(edge.vertices.count):
                v = edge.vertices.item(vi).geometry
                xs.append(v.x)
                ys.append(v.y)
                zs.append(v.z)
    except Exception:
        pass

    if not xs:
        return None

    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    # Avoid zero dimensions
    dx = max(dx, 1e-9)
    dy = max(dy, 1e-9)
    dz = max(dz, 1e-9)
    return dx, dy, dz


def validate_R005(design):
    """Check that no solid body has an excessively high bounding-box aspect ratio."""

    max_ratio     = 0.0
    worst_body    = "none"
    bodies_failed = 0
    bodies_total  = 0

    try:
        bodies = design.rootComponent.bRepBodies

        for bi in range(bodies.count):
            body = bodies.item(bi)
            if not body.isSolid:
                continue

            dims = _compute_bounding_box_dims(body)
            if dims is None:
                continue

            dx, dy, dz = dims
            sorted_dims = sorted([dx, dy, dz])
            if sorted_dims[0] == 0:
                continue

            ratio = sorted_dims[2] / sorted_dims[0]   # longest / shortest
            bodies_total += 1

            if ratio > max_ratio:
                max_ratio  = ratio
                worst_body = body.name

            if ratio > _REQUIRED_MAX_RATIO:
                bodies_failed += 1

    except Exception as exc:
        return {
            "passed":           False,
            "violation_detail": f"R005 scan error: {exc}",
            "actual_value":     0.0,
            "required_value":   _REQUIRED_MAX_RATIO,
            "unit":             _UNIT,
            "body_name":        "error",
        }

    if bodies_total == 0:
        return {
            "passed":           True,
            "violation_detail": "R005: No solid bodies found — skipped.",
            "actual_value":     -1.0,
            "required_value":   _REQUIRED_MAX_RATIO,
            "unit":             _UNIT,
            "body_name":        "none",
        }

    passed = max_ratio <= _REQUIRED_MAX_RATIO

    detail = (
        f"Max aspect ratio {max_ratio:.2f} "
        f"({'≤' if passed else '>'} limit {_REQUIRED_MAX_RATIO})"
        + (f", {bodies_failed} slender body/bodies" if not passed else "")
    )

    return {
        "passed":           passed,
        "violation_detail": detail,
        "actual_value":     round(max_ratio, 3),
        "required_value":   _REQUIRED_MAX_RATIO,
        "unit":             _UNIT,
        "body_name":        worst_body,
    }
