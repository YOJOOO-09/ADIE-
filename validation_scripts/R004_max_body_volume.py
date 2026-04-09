"""
ADIE — Auto-generated Validation Script
Rule ID  : R004
Rule     : max_body_volume
Value    : 1000000.0 mm3  (= 1000 cm3 = 1 litre)
Condition: (all solid bodies individually)
Severity : warning
Source   : page 12

CONTRACT:
    validate_R004(design) -> dict

METHOD:
    Uses physicalProperties.volume (Fusion returns cm³).
    Convert to mm³ (×1000).  Check each body individually.
    Reports the most-oversized body.
"""

_REQUIRED_MAX_MM3 = 1_000_000.0   # 1 litre in mm³
_UNIT             = "mm3"


def validate_R004(design):
    """Check that no single body exceeds the maximum allowed volume."""

    max_vol_mm3    = 0.0
    worst_body     = "none"
    bodies_checked = 0
    bodies_failed  = 0
    props_errors   = 0

    try:
        bodies = design.rootComponent.bRepBodies

        for bi in range(bodies.count):
            body = bodies.item(bi)
            if not body.isSolid:
                continue

            try:
                props = body.physicalProperties
                if props is None:
                    props_errors += 1
                    continue
                vol_cm3  = props.volume      # cm³
                vol_mm3  = vol_cm3 * 1000.0  # cm³ → mm³
                bodies_checked += 1

                if vol_mm3 > max_vol_mm3:
                    max_vol_mm3 = vol_mm3
                    worst_body  = body.name

                if vol_mm3 > _REQUIRED_MAX_MM3:
                    bodies_failed += 1

            except Exception:
                props_errors += 1
                continue

    except Exception as exc:
        return {
            "passed":           False,
            "violation_detail": f"R004 scan error: {exc}",
            "actual_value":     0.0,
            "required_value":   _REQUIRED_MAX_MM3,
            "unit":             _UNIT,
            "body_name":        "error",
        }

    if bodies_checked == 0:
        note = "no solid bodies" if props_errors == 0 else f"physicalProperties unavailable on {props_errors} body/bodies"
        return {
            "passed":           True,
            "violation_detail": f"R004: {note} — volume check skipped.",
            "actual_value":     -1.0,
            "required_value":   _REQUIRED_MAX_MM3,
            "unit":             _UNIT,
            "body_name":        "none",
        }

    passed = max_vol_mm3 <= _REQUIRED_MAX_MM3

    detail = (
        f"Largest body volume {max_vol_mm3:.1f}mm³ "
        f"({'≤' if passed else '>'} limit {_REQUIRED_MAX_MM3:.0f}mm³)"
        + (f", {bodies_failed} body/bodies exceed limit" if not passed else "")
    )

    return {
        "passed":           passed,
        "violation_detail": detail,
        "actual_value":     round(max_vol_mm3, 2),
        "required_value":   _REQUIRED_MAX_MM3,
        "unit":             _UNIT,
        "body_name":        worst_body,
    }
