"""
ADIE — Auto-generated Validation Script
Rule ID  : R001
Rule     : min_wall_thickness
Value    : 2.0 mm
Condition: material == Aluminum
Severity : critical
Source   : page 4 (ISO 2768 / general mechanical standard)

CONTRACT:
    validate_R001(design) -> dict
        design : adsk.fusion.Design  (injected by Fusion runtime)
    returns:
        passed           : bool
        violation_detail : str
        actual_value     : float   (mm)
        required_value   : float   (mm)
        unit             : str
        body_name        : str     (optional — used by Monitor)

METHOD:
    Proxy: minimum edge length across all solid BRep bodies.
    Short edges indicate thin features / thin walls.
    Fusion stores geometry in cm — convert ×10 to mm.

DO NOT EDIT — regenerate via synthesizer_agent.py if rule changes.
"""

# adsk is injected into this module's globals by monitor_agent before exec.
# No import statements needed.

_REQUIRED_MM = 2.0   # rule threshold
_UNIT        = "mm"


def validate_R001(design):
    """Check minimum wall thickness (via minimum edge length proxy)."""

    min_length_mm = float("inf")
    min_body_name = "none"
    total_edges   = 0

    try:
        root   = design.rootComponent
        bodies = root.bRepBodies

        for bi in range(bodies.count):
            body = bodies.item(bi)

            if not body.isSolid:
                continue

            edges = body.edges
            for ei in range(edges.count):
                edge = edges.item(ei)
                try:
                    length_mm = edge.length * 10.0  # cm → mm
                    total_edges += 1
                    if length_mm > 0 and length_mm < min_length_mm:
                        min_length_mm = length_mm
                        min_body_name = body.name
                except Exception:
                    continue

    except Exception as exc:
        return {
            "passed":           False,
            "violation_detail": f"R001 error during edge scan: {exc}",
            "actual_value":     0.0,
            "required_value":   _REQUIRED_MM,
            "unit":             _UNIT,
            "body_name":        "error",
        }

    if total_edges == 0 or min_length_mm == float("inf"):
        return {
            "passed":           True,
            "violation_detail": "R001: No solid edges found — skipped.",
            "actual_value":     -1.0,
            "required_value":   _REQUIRED_MM,
            "unit":             _UNIT,
            "body_name":        "none",
        }

    passed = min_length_mm >= _REQUIRED_MM

    detail = (
        f"Min edge length {min_length_mm:.3f}mm "
        f"{'≥' if passed else '<'} required {_REQUIRED_MM}mm "
        f"(wall thickness proxy, {total_edges} edges scanned)"
    )

    return {
        "passed":           passed,
        "violation_detail": detail,
        "actual_value":     round(min_length_mm, 4),
        "required_value":   _REQUIRED_MM,
        "unit":             _UNIT,
        "body_name":        min_body_name,
    }
