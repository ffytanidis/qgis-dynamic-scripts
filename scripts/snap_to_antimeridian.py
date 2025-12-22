import math
from qgis.utils import iface
from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes, Qgis
from qgis.PyQt.QtWidgets import QInputDialog, QProgressBar

# -------------------- UI helpers (Message Bar) --------------------
bar = iface.messageBar()

def msg_ok(text, duration=6):
    bar.pushMessage("Success", text, level=Qgis.Success, duration=duration)

def msg_warn(text, duration=7):
    bar.pushMessage("Warning", text, level=Qgis.Warning, duration=duration)

def msg_err(text, duration=9):
    bar.pushMessage("Error", text, level=Qgis.Critical, duration=duration)

# -------------------- Persistent "last tolerance" --------------------
# Stored as a dynamic attribute on iface for this QGIS session.
DEFAULT_TOL = getattr(iface, "_snap_dateline_last_tol", 0.007)

# -------------------- Preconditions (crash-safe) --------------------
progress_handle = None

try:
    layer = iface.activeLayer()
    if layer is None:
        msg_err("No active layer selected.")
        raise SystemExit

    if layer.crs().authid() != "EPSG:4326":
        msg_err(f"Layer CRS is {layer.crs().authid()}, expected EPSG:4326.")
        raise SystemExit

    if not layer.isEditable():
        msg_warn("Layer is not in edit mode. Enable editing and re-run.")
        raise SystemExit

    feats = list(layer.selectedFeatures())
    n = len(feats)
    if n == 0:
        msg_warn("No selected features.")
        raise SystemExit

    # -------------------- Input dialog --------------------
    prompt = (
        f"{n} selected feature(s) will be processed.\n\n"
        "Tolerance (degrees of longitude) for a vertex to snap:"
    )

    tolerance, ok = QInputDialog.getDouble(
        iface.mainWindow(),
        "Snap vertices to dateline (±180°)",
        prompt,
        value=float(DEFAULT_TOL),
        min=0.0,
        decimals=6
    )

    if not ok:
        msg_warn("Operation cancelled by user.")
        raise SystemExit

    # persist for next run (this QGIS session)
    setattr(iface, "_snap_dateline_last_tol", float(tolerance))

    # -------------------- Core snapping logic --------------------
    def snap_lon_to_dateline(x: float, tol: float) -> float:
        # Snap to +180 or -180 if within tolerance.
        if abs(x - 180.0) <= tol:
            return 180.0
        if abs(x + 180.0) <= tol:
            return -180.0
        return x

    def snap_outer_ring_only_polygon(poly_rings, tol: float):
        """
        poly_rings: list[rings] where ring is list[QgsPointXY]
        Only snaps vertices in the OUTER ring (index 0). Holes unchanged.
        Returns (new_poly_rings, snapped_count_for_this_poly)
        """
        if not poly_rings:
            return poly_rings, 0

        snapped = 0

        # Outer ring only
        outer = poly_rings[0]
        for i, pt in enumerate(outer):
            new_x = snap_lon_to_dateline(pt.x(), tol)
            if new_x != pt.x():
                outer[i] = QgsPointXY(new_x, pt.y())
                snapped += 1

        # Holes unchanged (poly_rings[1:])
        poly_rings[0] = outer
        return poly_rings, snapped

    def snap_poly_or_multipoly_outer_only(geom: QgsGeometry, tol: float):
        """
        Returns (new_geom, snapped_count). Only snaps OUTER rings, not holes.
        """
        if geom.isEmpty() or geom.type() != QgsWkbTypes.PolygonGeometry:
            return QgsGeometry(geom), 0

        total_snapped = 0

        if geom.isMultipart():
            mp = geom.asMultiPolygon()  # list[poly], poly=list[rings]
            for poly in mp:
                poly, s = snap_outer_ring_only_polygon(poly, tol)
                total_snapped += s
            new_geom = QgsGeometry.fromMultiPolygonXY(mp)
        else:
            poly = geom.asPolygon()
            poly, s = snap_outer_ring_only_polygon(poly, tol)
            total_snapped += s
            new_geom = QgsGeometry.fromPolygonXY(poly)

        return new_geom, total_snapped

    # -------------------- Progress bar --------------------
    progress_msg = bar.createMessage("Snapping outer-ring vertices to dateline…")
    progress = QProgressBar()
    progress.setMinimum(0)
    progress.setMaximum(n)
    progress.setValue(0)
    progress_msg.layout().addWidget(progress)
    progress_handle = bar.pushWidget(progress_msg, Qgis.Info)

    # -------------------- Apply edits --------------------
    layer.beginEditCommand("Snap selected features to dateline (±180°) [outer rings only]")

    touched_features = 0
    total_snapped_vertices = 0
    skipped_nonpoly = 0

    try:
        for i, f in enumerate(feats, start=1):
            g = f.geometry()
            if g.isEmpty() or g.type() != QgsWkbTypes.PolygonGeometry:
                skipped_nonpoly += 1
                progress.setValue(i)
                continue

            new_g, snapped = snap_poly_or_multipoly_outer_only(g, tolerance)

            if snapped > 0:
                layer.changeGeometry(f.id(), new_g)
                touched_features += 1
                total_snapped_vertices += snapped

            progress.setValue(i)

    finally:
        layer.endEditCommand()
        layer.triggerRepaint()

    # -------------------- Result messages --------------------
    if touched_features == 0:
        if skipped_nonpoly > 0:
            msg_warn(f"Finished. No vertices snapped. Skipped {skipped_nonpoly} non-polygon/empty feature(s).")
        else:
            msg_warn("Finished. No vertices were within tolerance to snap.")
    else:
        msg_ok(
            f"Finished. Modified {touched_features}/{n} feature(s); "
            f"snapped {total_snapped_vertices} outer-ring vertex/vertices. "
            "Edits are NOT saved."
        )

except SystemExit:
    pass
except Exception as e:
    msg_err(f"Unexpected error: {e}")
finally:
    if progress_handle is not None:
        try:
            bar.popWidget(progress_handle)
        except Exception:
            pass
