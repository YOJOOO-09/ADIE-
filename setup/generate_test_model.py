"""
ADIE — Generate Test Model Script
Run this inside Fusion 360: Tools → Scripts and Add-Ins → Scripts → Add → Run

Creates a solid box (100mm × 80mm × 50mm) with a cylindrical hole (diameter 20mm)
so ADIE has real geometry to validate against its engineering rules.
"""

import traceback

try:
    import adsk.core
    import adsk.fusion
    import adsk.cam
except ImportError:
    print("ERROR: Run this script inside Fusion 360.")


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)

        if not design:
            ui.messageBox("No active Fusion design found. Open a design first.")
            return

        root = design.rootComponent

        # ── Step 1: Create a sketch on the XY plane ──────────────────────────
        xy_plane = root.xYConstructionPlane
        sketch = root.sketches.add(xy_plane)

        # Draw a 100mm × 80mm rectangle
        lines = sketch.sketchCurves.sketchLines
        p0 = adsk.core.Point3D.create(0, 0, 0)
        p1 = adsk.core.Point3D.create(10, 0, 0)   # 100mm = 10cm in Fusion
        p2 = adsk.core.Point3D.create(10, 8, 0)   # 80mm  = 8cm
        p3 = adsk.core.Point3D.create(0, 8, 0)

        lines.addByTwoPoints(p0, p1)
        lines.addByTwoPoints(p1, p2)
        lines.addByTwoPoints(p2, p3)
        lines.addByTwoPoints(p3, p0)

        # ── Step 2: Extrude to 50mm ───────────────────────────────────────────
        prof = sketch.profiles.item(0)
        extrudes = root.features.extrudeFeatures
        ext_input = extrudes.createInput(
            prof,
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )
        dist = adsk.core.ValueInput.createByReal(5.0)   # 50mm = 5cm
        ext_input.setDistanceExtent(False, dist)
        box = extrudes.add(ext_input)

        # ── Step 3: Add a cylindrical hole (diameter 20mm, depth 30mm) ────────
        # Draw circle on top face of the box
        top_face = None
        for i in range(box.bodies.item(0).faces.count):
            face = box.bodies.item(0).faces.item(i)
            if abs(face.boundingBox.maxPoint.z - 5.0) < 0.01:
                top_face = face
                break

        if top_face:
            sketch2 = root.sketches.add(top_face)
            center = adsk.core.Point3D.create(5, 4, 0)   # center of top face
            sketch2.sketchCurves.sketchCircles.addByCenterRadius(center, 1.0)  # r=1cm=10mm → dia=20mm

            prof2 = sketch2.profiles.item(0)
            ext_input2 = extrudes.createInput(
                prof2,
                adsk.fusion.FeatureOperations.CutFeatureOperation
            )
            dist2 = adsk.core.ValueInput.createByReal(3.0)   # 30mm deep
            ext_input2.setDistanceExtent(False, dist2)
            extrudes.add(ext_input2)

        # ── Step 4: Report ────────────────────────────────────────────────────
        body = root.bRepBodies.item(0)
        vol  = round(body.physicalProperties.volume, 4)

        msg = (
            "✅  Test model created!\n\n"
            f"  Body name : {body.name}\n"
            f"  Volume    : {vol} cm³\n"
            f"  Size      : 100mm × 80mm × 50mm\n"
            f"  Hole      : ⌀20mm × 30mm deep\n\n"
            "Now press  Cmd+S  to save.\n"
            "ADIE will automatically validate the design."
        )
        ui.messageBox(msg, "ADIE — Test Model Ready")

    except Exception:
        msg = traceback.format_exc()
        print(f"generate_test_model error:\n{msg}")
        if ui:
            ui.messageBox(f"Error:\n{msg}", "ADIE Script Error")


def stop(context):
    pass
