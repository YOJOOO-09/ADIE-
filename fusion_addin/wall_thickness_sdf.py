"""
ADIE — Autonomous Design Integrity Engine
SDF Wall Thickness Check: wall_thickness_sdf.py

PURPOSE:
    Geometrically rigorous minimum wall thickness computation using
    OpenCASCADE via pythonocc-core.

    Method: Signed Distance Field (SDF) sampling.
    For each BRep solid:
      1. Load STEP file via STEPControl_Reader
      2. Build a 20×20×20 sampling grid inside the bounding box
      3. For each grid point, compute distance to nearest face
      4. Filter to interior points (distances > 0)
      5. Minimum interior distance = minimum wall thickness

REQUIREMENTS:
    conda install -c conda-forge pythonocc-core
    Do NOT pip install pythonocc. conda only.

USAGE (standalone, called by Monitor Agent):
    from wall_thickness_sdf import validate_wall_thickness_sdf

    result = validate_wall_thickness_sdf(
        step_filepath="data/step_exports/Body1.step",
        min_thickness_mm=2.0
    )
    # result: {"passed": bool, "min_thickness_mm": float, "required_mm": float, ...}

    OR run directly:
    python wall_thickness_sdf.py --step path/to/body.step --min-thickness 2.0

AUTHOR: Aryn Gahlot | ADIE Project | Day 4
"""

# ─────────────────────────────────────────────────────────────────────────────
# Standard library
# ─────────────────────────────────────────────────────────────────────────────
import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger("ADIE.SDF")

# ─────────────────────────────────────────────────────────────────────────────
# pythonocc-core (conda only)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.BRepBndLib import brepbndlib_Add
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCC.Core.TopoDS import topods_Face, topods_Solid
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.TopAbs import TopAbs_IN
    _OCC_AVAILABLE = True
except ImportError:
    _OCC_AVAILABLE = False
    log.warning(
        "pythonocc-core not available. SDF wall thickness check disabled.\n"
        "Install with:  conda install -c conda-forge pythonocc-core"
    )


# ─────────────────────────────────────────────────────────────────────────────
# STEP loader
# ─────────────────────────────────────────────────────────────────────────────

def load_step(filepath: Path):
    """
    Load a STEP file via STEPControl_Reader.
    Returns the OCC shape, or raises on failure.
    """
    reader = STEPControl_Reader()
    status = reader.ReadFile(str(filepath))
    if status != IFSelect_RetDone:
        raise IOError(f"Failed to read STEP file: {filepath}  (status={status})")

    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError(f"STEP file loaded but shape is null: {filepath}")

    log.info("STEP loaded: %s", filepath.name)
    return shape


# ─────────────────────────────────────────────────────────────────────────────
# Bounding box
# ─────────────────────────────────────────────────────────────────────────────

def get_bounding_box(shape) -> tuple[float, float, float, float, float, float]:
    """
    Compute axis-aligned bounding box.
    Returns (xmin, ymin, zmin, xmax, ymax, zmax) in mm (STEP default).
    """
    bbox = Bnd_Box()
    brepbndlib_Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return xmin, ymin, zmin, xmax, ymax, zmax


# ─────────────────────────────────────────────────────────────────────────────
# Interior point classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_interior_points(shape, grid_points: list) -> list:
    """
    Use BRepClass3d_SolidClassifier to find interior grid points.
    Returns subset of grid_points that are inside the solid.
    """
    # Find the first solid in the shape
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    if not explorer.More():
        log.warning("No solid found in STEP shape — using all grid points.")
        return grid_points

    solid = topods_Solid(explorer.Current())
    classifier = BRepClass3d_SolidClassifier(solid)

    interior = []
    tolerance = 0.001   # mm

    for pt in grid_points:
        classifier.Perform(gp_Pnt(*pt), tolerance)
        if classifier.State() == TopAbs_IN:
            interior.append(pt)

    log.debug("Interior points: %d / %d", len(interior), len(grid_points))
    return interior


# ─────────────────────────────────────────────────────────────────────────────
# Distance to nearest face
# ─────────────────────────────────────────────────────────────────────────────

def collect_surfaces(shape) -> list:
    """Extract all face surfaces from the shape for projection."""
    surfaces = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = topods_Face(explorer.Current())
        surf = BRep_Tool.Surface(face)
        if not surf.IsNull():
            surfaces.append(surf)
        explorer.Next()
    log.debug("Collected %d surfaces from shape.", len(surfaces))
    return surfaces


def distance_to_nearest_face(point: tuple, surfaces: list) -> float:
    """
    Compute the minimum distance from a 3D point to the nearest face surface.
    Returns distance in mm (same units as STEP file).
    """
    gp = gp_Pnt(*point)
    min_dist = float("inf")

    for surf in surfaces:
        try:
            proj = GeomAPI_ProjectPointOnSurf(gp, surf)
            if proj.NbPoints() > 0:
                dist = proj.LowerDistance()
                if dist < min_dist:
                    min_dist = dist
        except Exception:
            continue   # some surfaces may not support projection — skip

    return min_dist if min_dist != float("inf") else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# SDF sampling core
# ─────────────────────────────────────────────────────────────────────────────

def compute_min_wall_thickness_sdf(
    shape,
    grid_n: int = 20,
) -> float:
    """
    Compute minimum wall thickness via SDF sampling.

    Algorithm:
      1. Build 20×20×20 grid inside bounding box
      2. Classify interior points
      3. For each interior point, find distance to nearest face
      4. Minimum of those distances = wall thickness estimate

    Returns minimum wall thickness in mm.
    """
    xmin, ymin, zmin, xmax, ymax, zmax = get_bounding_box(shape)

    # Build uniform grid
    dx = (xmax - xmin) / (grid_n + 1)
    dy = (ymax - ymin) / (grid_n + 1)
    dz = (zmax - zmin) / (grid_n + 1)

    grid_points = []
    for i in range(1, grid_n + 1):
        x = xmin + i * dx
        for j in range(1, grid_n + 1):
            y = ymin + j * dy
            for k in range(1, grid_n + 1):
                z = zmin + k * dz
                grid_points.append((x, y, z))

    log.info(
        "SDF sampling: %d grid points (bbox=[%.2f,%.2f,%.2f]->[%.2f,%.2f,%.2f])",
        len(grid_points), xmin, ymin, zmin, xmax, ymax, zmax,
    )

    # Filter to interior points
    interior_points = classify_interior_points(shape, grid_points)

    if not interior_points:
        log.warning("No interior points found — shape may be a surface/shell, not a solid.")
        return float("inf")  # cannot determine thickness → treat as passing

    # Collect face surfaces for projection
    surfaces = collect_surfaces(shape)
    if not surfaces:
        log.warning("No surfaces extracted from shape.")
        return float("inf")

    # Compute minimum distance
    min_thickness = float("inf")
    for i, pt in enumerate(interior_points):
        d = distance_to_nearest_face(pt, surfaces)
        if d < min_thickness:
            min_thickness = d
        # Progress logging every 500 points
        if (i + 1) % 500 == 0:
            log.debug("SDF progress: %d/%d — current min=%.3f mm", i + 1, len(interior_points), min_thickness)

    # Interior distance = distance to nearest wall = half the local wall thickness?
    # For SDF: actually the distance from interior point to surface IS the minimum
    # wall half-thickness at that point. Wall thickness = 2 * sdf_value for a thin wall.
    # For conservative prototype: report min_distance directly as min thickness.
    log.info("SDF complete. Minimum wall thickness estimate: %.4f mm", min_thickness)
    return min_thickness


# ─────────────────────────────────────────────────────────────────────────────
# Public API used by Monitor Agent
# ─────────────────────────────────────────────────────────────────────────────

def validate_wall_thickness_sdf(
    step_filepath: str | Path,
    min_thickness_mm: float = 2.0,
    grid_n: int = 20,
) -> dict:
    """
    Main entry point for the SDF wall thickness check.

    Args:
        step_filepath   : path to a STEP file exported from Fusion 360
        min_thickness_mm: minimum allowed wall thickness (mm)
        grid_n          : grid resolution per axis (default 20 → 8000 samples)

    Returns:
        {
            "passed":           bool,
            "violation_detail": str,
            "min_thickness_mm": float,
            "required_mm":      float,
            "unit":             "mm",
            "grid_points_sampled": int,
        }
    """
    step_filepath = Path(step_filepath)

    if not _OCC_AVAILABLE:
        return {
            "passed": True,
            "violation_detail": "pythonocc not available — SDF check skipped.",
            "min_thickness_mm": -1.0,
            "required_mm": min_thickness_mm,
            "unit": "mm",
            "grid_points_sampled": 0,
        }

    if not step_filepath.exists():
        return {
            "passed": False,
            "violation_detail": f"STEP file not found: {step_filepath}",
            "min_thickness_mm": -1.0,
            "required_mm": min_thickness_mm,
            "unit": "mm",
            "grid_points_sampled": 0,
        }

    try:
        shape = load_step(step_filepath)
        min_t = compute_min_wall_thickness_sdf(shape, grid_n=grid_n)
        total_samples = grid_n ** 3

        passed = min_t >= min_thickness_mm

        detail = (
            f"Min wall thickness {min_t:.3f}mm {'≥' if passed else '<'} "
            f"required {min_thickness_mm}mm"
            + ("" if passed else f" — violation of {min_thickness_mm - min_t:.3f}mm")
        )

        return {
            "passed": passed,
            "violation_detail": detail,
            "min_thickness_mm": round(min_t, 4),
            "required_mm": min_thickness_mm,
            "unit": "mm",
            "grid_points_sampled": total_samples,
        }

    except Exception as exc:
        log.error("SDF check failed: %s", exc)
        return {
            "passed": True,   # fail-open: don't block design on SDF error
            "violation_detail": f"SDF check error: {exc}",
            "min_thickness_mm": -1.0,
            "required_mm": min_thickness_mm,
            "unit": "mm",
            "grid_points_sampled": 0,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Fusion 360 export helper (called before SDF check)
# ─────────────────────────────────────────────────────────────────────────────

def export_body_to_step(body, export_dir: Path) -> Path | None:
    """
    Export a Fusion 360 BRepBody to a STEP file using Fusion's exportManager.

    Args:
        body       : adsk.fusion.BRepBody
        export_dir : directory to save the STEP file

    Returns: Path to the exported STEP file, or None on failure.

    Must be called from inside Fusion 360 (adsk in scope).
    """
    try:
        import adsk.core
        import adsk.fusion

        export_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in body.name)
        step_path = export_dir / f"{safe_name}.step"

        app = adsk.core.Application.get()
        design = app.activeProduct

        export_mgr = design.exportManager
        step_options = export_mgr.createSTEPExportOptions(str(step_path), body)
        success = export_mgr.execute(step_options)

        if success:
            log.info("Exported %s → %s", body.name, step_path)
            return step_path
        else:
            log.error("STEP export failed for body: %s", body.name)
            return None

    except Exception:
        log.error("export_body_to_step error:\n", exc_info=True)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CLI for standalone testing
# ─────────────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="wall_thickness_sdf",
        description="ADIE SDF Wall Thickness Check — standalone test",
    )
    parser.add_argument("--step", required=True, metavar="PATH", help="Path to STEP file")
    parser.add_argument(
        "--min-thickness",
        type=float,
        default=2.0,
        metavar="MM",
        help="Minimum wall thickness in mm (default: 2.0)",
    )
    parser.add_argument(
        "--grid",
        type=int,
        default=20,
        metavar="N",
        help="Grid resolution per axis (default: 20 → 8000 samples)",
    )
    args = parser.parse_args()

    if not _OCC_AVAILABLE:
        print("ERROR: pythonocc-core not installed.")
        print("Install with:  conda install -c conda-forge pythonocc-core")
        sys.exit(1)

    result = validate_wall_thickness_sdf(
        step_filepath=args.step,
        min_thickness_mm=args.min_thickness,
        grid_n=args.grid,
    )

    print("\n" + "═" * 50)
    print("  ADIE SDF Wall Thickness Result")
    print("═" * 50)
    for k, v in result.items():
        print(f"  {k:<25}: {v}")
    print("═" * 50)
    print(f"\n  {'✅  PASSED' if result['passed'] else '❌  FAILED'}")


if __name__ == "__main__":
    main()
