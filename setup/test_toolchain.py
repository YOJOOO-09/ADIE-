"""
ADIE — Autonomous Design Integrity Engine
Day 1: test_toolchain.py

PURPOSE:
    Validates that the Fusion 360 Python environment is operational.
    Iterates all BRep bodies in the active design, prints name, volume,
    and material availability. Run this script inside Fusion 360's
    Script Editor (or as an add-in) to verify the toolchain.

USAGE:
    In Fusion 360: Tools → Scripts and Add-ins → Scripts → Add → browse to this file → Run
    adsk is already in scope inside Fusion's Python interpreter.

AUTHOR: Aryn Gahlot | ADIE Project | Day 1
"""

# ─────────────────────────────────────────────────────────────────────────────
# Standard library
# ─────────────────────────────────────────────────────────────────────────────
import traceback
from datetime import datetime, timezone

# adsk is injected by Fusion 360's runtime — do not import it manually.
# We reference it via globals() guard so this file can also be syntax-checked
# outside Fusion without crashing on import.
try:
    import adsk.core
    import adsk.fusion
    _ADSK_AVAILABLE = True
except ImportError:
    _ADSK_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _separator(char: str = "─", width: int = 60) -> str:
    return char * width


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _get_physical_volume(body) -> tuple[float | None, str]:
    """
    Attempt to read physicalProperties.volume from a BRepBody.

    Returns (volume_cm3, status_string) where volume_cm3 is None if
    properties are unavailable (e.g. not computed yet or body is lightweight).
    Volume from Fusion API is in cm³.
    """
    try:
        props = body.physicalProperties
        if props is None:
            return None, "physicalProperties returned None"
        vol = props.volume          # cm³
        return vol, "OK"
    except Exception as exc:       # noqa: BLE001
        return None, f"ERROR: {exc}"


def _material_name(body) -> str:
    """Return material name if assigned, else '<none>'."""
    try:
        mat = body.material
        if mat and mat.name:
            return mat.name
    except Exception:               # noqa: BLE001
        pass
    return "<none>"


# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

def inspect_active_design() -> dict:
    """
    Main inspection routine.

    Returns a summary dict:
        {
            "success": bool,
            "design_name": str,
            "body_count": int,
            "bodies": [{"name": str, "volume_cm3": float|None, "material": str, "props_status": str}],
            "errors": [str],
            "timestamp": str
        }
    """
    result = {
        "success": False,
        "design_name": "<unknown>",
        "body_count": 0,
        "bodies": [],
        "errors": [],
        "timestamp": _now_iso(),
    }

    # ── Step 1: acquire Application handle ───────────────────────────────────
    app = adsk.core.Application.get()
    if app is None:
        result["errors"].append("adsk.core.Application.get() returned None — Fusion not running?")
        return result

    # ── Step 2: get active product and cast to Design ─────────────────────────
    product = app.activeProduct
    if product is None:
        result["errors"].append("app.activeProduct is None — no document is open.")
        return result

    if not isinstance(product, adsk.fusion.Design):
        result["errors"].append(
            f"Active product is '{type(product).__name__}', not a Fusion Design. "
            "Open a Fusion 360 design (.f3d) and retry."
        )
        return result

    design: adsk.fusion.Design = product
    result["design_name"] = design.rootComponent.name or "<unnamed>"

    # ── Step 3: iterate BRep bodies ──────────────────────────────────────────
    bodies = design.rootComponent.bRepBodies
    result["body_count"] = bodies.count

    for i in range(bodies.count):
        body = bodies.item(i)
        volume, props_status = _get_physical_volume(body)
        material = _material_name(body)

        body_info = {
            "index": i + 1,
            "name": body.name,
            "volume_cm3": round(volume, 6) if volume is not None else None,
            "material": material,
            "props_status": props_status,
            "is_solid": body.isSolid if hasattr(body, "isSolid") else "<unknown>",
        }
        result["bodies"].append(body_info)

    result["success"] = True
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Report printer
# ─────────────────────────────────────────────────────────────────────────────

def print_report(result: dict) -> None:
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
    except Exception:
        pass

    lines = []
    lines.append(_separator("═"))
    lines.append("  ADIE — Toolchain Test Report")
    lines.append(f"  Timestamp : {result['timestamp']}")
    lines.append(f"  Design    : {result['design_name']}")
    lines.append(f"  Bodies    : {result['body_count']}")
    lines.append(_separator("─"))

    if not result["success"]:
        lines.append("  STATUS : ❌  FAILED")
        for err in result["errors"]:
            lines.append(f"  ERROR  : {err}")
    else:
        lines.append("  STATUS : ✅  SUCCESS")
        lines.append("")

        if result["body_count"] == 0:
            lines.append("  ⚠  No BRep bodies found in rootComponent.")
            lines.append("     Open a design that has at least one solid body.")
        else:
            header = f"  {'#':<4}  {'Body Name':<28}  {'Volume (cm³)':>14}  {'Material':<20}  Props"
            lines.append(header)
            lines.append(_separator("·"))
            for b in result["bodies"]:
                vol_str = f"{b['volume_cm3']:>14.4f}" if b["volume_cm3"] is not None else f"  {'N/A':>12}"
                lines.append(
                    f"  {b['index']:<4}  {b['name']:<28}  {vol_str}  {b['material']:<20}  {b['props_status']}"
                )

    lines.append(_separator("═"))
    lines.append("  ADIE Day 1 toolchain check complete.")
    lines.append(_separator("═"))

    report_text = "\n".join(lines)

    # Print to Fusion's TextCommandPalette (visible in the Console)
    try:
        palette = ui.palettes.itemById("TextCommands") if ui else None
        if palette:
            palette.isVisible = True
            palette.writeText(report_text)
    except Exception:
        pass

    # Also print to stdout (captured by Fusion's script output window)
    print(report_text)


# ─────────────────────────────────────────────────────────────────────────────
# Fusion 360 add-in entry points
# ─────────────────────────────────────────────────────────────────────────────

def run(context):
    """Entry point called by Fusion 360 when the script/add-in is run."""
    ui = None
    try:
        if not _ADSK_AVAILABLE:
            print("ERROR: adsk modules not available. Run this script inside Fusion 360.")
            return

        result = inspect_active_design()
        print_report(result)

        # Surface a modal alert for critical failures so they are not missed.
        app = adsk.core.Application.get()
        if app:
            ui = app.userInterface
            if not result["success"] and ui:
                ui.messageBox(
                    "ADIE Toolchain Test FAILED.\n\n" + "\n".join(result["errors"]),
                    "ADIE — Day 1 Check",
                    adsk.core.MessageBoxButtonTypes.OKButtonType,
                    adsk.core.MessageBoxIconTypes.CriticalIconType,
                )
            elif result["success"] and result["body_count"] > 0 and ui:
                ui.messageBox(
                    f"✅ Toolchain OK.\n"
                    f"Found {result['body_count']} body/bodies in '{result['design_name']}'.\n"
                    "Check the Script Console for the full report.",
                    "ADIE — Day 1 Check",
                    adsk.core.MessageBoxButtonTypes.OKButtonType,
                    adsk.core.MessageBoxIconTypes.InformationIconType,
                )

    except Exception:
        msg = traceback.format_exc()
        print(f"ADIE test_toolchain UNHANDLED EXCEPTION:\n{msg}")
        if ui:
            try:
                ui.messageBox(f"Unhandled exception:\n{msg}", "ADIE Error")
            except Exception:
                pass


def stop(context):
    """Called by Fusion 360 when the add-in is stopped. Nothing to clean up."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Standalone guard — allows syntax/AST validation outside Fusion
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _ADSK_AVAILABLE:
        print("=" * 60)
        print("  ADIE test_toolchain.py — standalone syntax check")
        print("  adsk not available outside Fusion 360.")
        print("  Run this file via Fusion 360 Script Editor for real output.")
        print("=" * 60)
    else:
        # If somehow adsk is available in a standalone context, run it.
        result = inspect_active_design()
        print_report(result)
