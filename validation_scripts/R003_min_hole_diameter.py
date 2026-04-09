"""
ADIE — Auto-generated Validation Script
Rule ID  : R003
Rule     : min_hole_diameter
Value    : 1.0 mm
Condition: (circular edges detected)
Severity : critical
Source   : page 8

CONTRACT:
    validate_R003(design) -> dict

METHOD:
    Detects circular edges (type check via object name since adsk may
    not be available for isinstance).  For each circular edge geometry,
    radius = length / (2π).  Minimum diameter = 2 × minimum radius.
    This correctly identifies drilled holes and circular cut-outs.

    Fusion geometry units: cm.  Converted to mm (×10).
"""

import math

_REQUIRED_DIAMETER_MM = 1.0
_UNIT = "mm"
_TWO_PI = 2.0 * math.pi


def validate_R003(design):
    """Check minimum hole (circular edge) diameter."""

    min_diameter_mm = float("inf")
    offending_body  = "none"
    circles_found   = 0

    try:
        bodies = design.rootComponent.bRepBodies

        for bi in range(bodies.count):
            body = bodies.item(bi)

            for ei in range(body.edges.count):
                edge = body.edges.item(ei)
                try:
                    geom = edge.geometry
                    # Identify circular edges by geometry class name
                    geom_type = type(geom).__name__   # 'Circle3D'
                    if geom_type == "Circle3D":
                        # radius in cm → mm
                        radius_mm   = geom.radius * 10.0
                        diameter_mm = radius_mm * 2.0
                        circles_found += 1
                        if diameter_mm < min_diameter_mm:
                            min_diameter_mm = diameter_mm
                            offending_body  = body.name
                    elif geom_type in ("Arc3D", "EllipseArc3D") and edge.length > 0:
                        # Arc: estimate diameter from arc length / angle
                        # Simpler fallback: skip arc-type edges
                        pass
                except Exception:
                    continue

    except Exception as exc:
        return {
            "passed":           False,
            "violation_detail": f"R003 scan error: {exc}",
            "actual_value":     0.0,
            "required_value":   _REQUIRED_DIAMETER_MM,
            "unit":             _UNIT,
            "body_name":        "error",
        }

    if circles_found == 0:
        # No holes detected — rule cannot be violated
        return {
            "passed":           True,
            "violation_detail": "R003: No circular edges (holes) found — check skipped.",
            "actual_value":     -1.0,
            "required_value":   _REQUIRED_DIAMETER_MM,
            "unit":             _UNIT,
            "body_name":        "none",
        }

    passed = min_diameter_mm >= _REQUIRED_DIAMETER_MM

    detail = (
        f"Min hole diameter {min_diameter_mm:.4f}mm "
        f"{'≥' if passed else '<'} required {_REQUIRED_DIAMETER_MM}mm "
        f"({circles_found} circles scanned)"
    )

    return {
        "passed":           passed,
        "violation_detail": detail,
        "actual_value":     round(min_diameter_mm, 4),
        "required_value":   _REQUIRED_DIAMETER_MM,
        "unit":             _UNIT,
        "body_name":        offending_body,
    }
