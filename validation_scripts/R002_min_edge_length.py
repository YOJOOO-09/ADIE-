"""
ADIE — Auto-generated Validation Script
Rule ID  : R002
Rule     : min_edge_length
Value    : 0.5 mm
Condition: (all solid bodies)
Severity : warning
Source   : page 6

CONTRACT:
    validate_R002(design) -> dict

METHOD:
    Finds the absolute minimum edge length across all BRep bodies.
    Very short edges indicate sliver geometry that causes CAM / FEA issues.
    Fusion stores lengths in cm — multiply by 10 for mm.
"""

_REQUIRED_MM = 0.5
_UNIT        = "mm"


def validate_R002(design):
    """Check that no edge is shorter than the minimum allowable length."""

    global_min_mm  = float("inf")
    offending_body = "none"
    offending_count = 0

    try:
        bodies = design.rootComponent.bRepBodies

        for bi in range(bodies.count):
            body = bodies.item(bi)

            for ei in range(body.edges.count):
                try:
                    length_mm = body.edges.item(ei).length * 10.0
                    if length_mm <= 0:
                        continue
                    if length_mm < _REQUIRED_MM:
                        offending_count += 1
                    if length_mm < global_min_mm:
                        global_min_mm  = length_mm
                        offending_body = body.name
                except Exception:
                    continue

    except Exception as exc:
        return {
            "passed":           False,
            "violation_detail": f"R002 scan error: {exc}",
            "actual_value":     0.0,
            "required_value":   _REQUIRED_MM,
            "unit":             _UNIT,
            "body_name":        "error",
        }

    if global_min_mm == float("inf"):
        return {
            "passed":           True,
            "violation_detail": "R002: No edges found.",
            "actual_value":     -1.0,
            "required_value":   _REQUIRED_MM,
            "unit":             _UNIT,
            "body_name":        "none",
        }

    passed = global_min_mm >= _REQUIRED_MM

    detail = (
        f"Shortest edge {global_min_mm:.4f}mm "
        f"{'≥' if passed else '<'} required {_REQUIRED_MM}mm"
        + (f", {offending_count} short edges found" if not passed else "")
    )

    return {
        "passed":           passed,
        "violation_detail": detail,
        "actual_value":     round(global_min_mm, 4),
        "required_value":   _REQUIRED_MM,
        "unit":             _UNIT,
        "body_name":        offending_body,
    }
