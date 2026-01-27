import math
from pyproj import Transformer
from qgis.PyQt.QtWidgets import QInputDialog, QProgressBar, QMessageBox
from qgis.core import QgsWkbTypes, QgsGeometry, QgsPointXY, Qgis
from qgis.utils import iface

bar = iface.messageBar()

def _msg(title, text, level, duration):
    bar.pushMessage(title, text, level=level, duration=duration)

msg_ok   = lambda t, d=5: _msg("Success", t, Qgis.Success, d)
msg_warn = lambda t, d=6: _msg("Warning", t, Qgis.Warning, d)
msg_err  = lambda t, d=8: _msg("Error",   t, Qgis.Critical, d)

# Transformers (EPSG:4326 <-> EPSG:3857)
to_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
to_4326 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform

hypot = math.hypot
Qpt = QgsPointXY


# =========================
# Douglas–Peucker (planar)
# =========================
def _perp_dist_point_to_line(px, py, ax, ay, bx, by):
    """Perpendicular distance from P to segment AB in planar coords."""
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return hypot(px - ax, py - ay)

    # projection parameter t on infinite line, clamped to segment
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    if t <= 0.0:
        cx, cy = ax, ay
    elif t >= 1.0:
        cx, cy = bx, by
    else:
        cx, cy = ax + t * dx, ay + t * dy
    return hypot(px - cx, py - cy)

def _dp_simplify_xy(points_xy, tol_m):
    """
    Douglas–Peucker simplification for a polyline in planar coords.
    points_xy: list[(x,y)] length >= 2
    Returns list[(x,y)] of kept points (in original order).
    """
    n = len(points_xy)
    if n <= 2:
        return points_xy

    keep = [False] * n
    keep[0] = keep[-1] = True

    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        ax, ay = points_xy[i0]
        bx, by = points_xy[i1]

        max_d = -1.0
        idx = -1
        # find farthest point from segment
        for i in range(i0 + 1, i1):
            px, py = points_xy[i]
            d = _perp_dist_point_to_line(px, py, ax, ay, bx, by)
            if d > max_d:
                max_d = d
                idx = i

        if max_d > tol_m and idx != -1:
            keep[idx] = True
            stack.append((i0, idx))
            stack.append((idx, i1))

    return [pt for k, pt in zip(keep, points_xy) if k]

def _is_closed_ring_pts(ring_pts):
    return bool(ring_pts) and ring_pts[0] == ring_pts[-1]

def simplify_ring_dp_3857(ring_pts, tol_m, min_pts=4):
    """
    Simplify a closed ring (list of QgsPointXY) using Douglas–Peucker in EPSG:3857.
    Keeps closure and enforces a minimum number of points (default 4 incl. closure).
    Returns (new_ring_pts, changed_bool).
    """
    if not ring_pts or len(ring_pts) < 4:
        return ring_pts, False

    closed = _is_closed_ring_pts(ring_pts)
    if not closed:
        # assuming valid geometries, but guard anyway
        ring_pts = ring_pts + [ring_pts[0]]

    # Work on open ring (exclude duplicate last point)
    core = ring_pts[:-1]
    if len(core) < 3:
        return ring_pts, False

    # project to 3857
    pts_3857 = [to_3857(p.x(), p.y()) for p in core]

    # simplify
    simp_3857 = _dp_simplify_xy(pts_3857, tol_m)

    # enforce minimum points (a valid ring needs at least 3 distinct + closure)
    if len(simp_3857) < (min_pts - 1):
        simp_3857 = pts_3857  # revert (too aggressive)

    # back to 4326 and re-close
    simp_4326 = [Qpt(*to_4326(x, y)) for (x, y) in simp_3857]
    simp_4326.append(simp_4326[0])

    changed = len(simp_4326) != len(ring_pts)
    return simp_4326, changed

def simplify_poly_or_mpoly_dp_3857(geom, tol_m):
    """
    Simplify Polygon/MultiPolygon using DP per ring in EPSG:3857.
    Returns (new_geom, changed_bool).
    """
    if geom.isEmpty() or geom.type() != QgsWkbTypes.PolygonGeometry:
        return QgsGeometry(geom), False

    polys = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
    new_mp = []
    changed_any = False

    for poly in polys:
        if not poly:
            continue

        ext, ch_ext = simplify_ring_dp_3857(poly[0], tol_m)
        changed_any = changed_any or ch_ext

        holes = []
        for hole in poly[1:]:
            h, ch_h = simplify_ring_dp_3857(hole, tol_m)
            changed_any = changed_any or ch_h
            holes.append(h)

        new_mp.append([ext] + holes)

    return (QgsGeometry.fromMultiPolygonXY(new_mp), changed_any) if new_mp else (QgsGeometry(), changed_any)


# ---- MAIN (crash-safe) ----
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

    sel_count = layer.selectedFeatureCount()
    apply_all = False

    if sel_count == 0:
        ans = QMessageBox.question(
            iface.mainWindow(),
            "No selection",
            "No features are selected.\n\nApply simplification to ALL features of the active layer?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ans != QMessageBox.Yes:
            msg_warn("Operation cancelled.")
            raise SystemExit
        apply_all = True

    n = int(layer.featureCount()) if apply_all else int(sel_count)
    if n == 0:
        msg_warn("No features to process.")
        raise SystemExit

    # Simple prompt text (as requested)
    tol_m, ok = QInputDialog.getDouble(
        iface.mainWindow(),
        "Mercator (EPSG:3857) simplify polygons",
        f"{n} feature(s) will be simplified.\n\nEnter simplification tolerance (meters):",
        value=50.0,
        min=0.0,
        decimals=3
    )
    if not ok:
        msg_warn("Operation cancelled by user.")
        raise SystemExit

    if tol_m <= 0.0:
        msg_warn("Tolerance is 0. No changes were made.")
        raise SystemExit

    # Progress bar
    progress_msg = bar.createMessage("Simplifying features…")
    progress = QProgressBar()
    progress.setRange(0, n)
    progress.setValue(0)
    progress_msg.layout().addWidget(progress)
    progress_handle = bar.pushWidget(progress_msg, Qgis.Info)

    changed = skipped = 0

    # Micro-optimizations: localize hot callables
    set_prog = progress.setValue
    change_geom = layer.changeGeometry

    layer.beginEditCommand("Douglas–Peucker simplify polygons (EPSG:3857)")
    try:
        it = layer.getFeatures() if apply_all else layer.getSelectedFeatures()
        for i, f in enumerate(it, start=1):
            g = f.geometry()
            if g.isEmpty() or g.type() != QgsWkbTypes.PolygonGeometry:
                skipped += 1
                set_prog(i)
                continue

            ng, did_change = simplify_poly_or_mpoly_dp_3857(g, tol_m)
            if did_change:
                change_geom(f.id(), ng)
                changed += 1

            set_prog(i)
    finally:
        layer.endEditCommand()
        layer.triggerRepaint()

    if changed == 0 and skipped == 0:
        msg_warn("Finished. No geometry changes were necessary.")
    elif changed == 0:
        msg_warn(f"Finished. No geometries changed. Skipped {skipped} feature(s).")
    else:
        msg_ok(f"Finished. Modified {changed} of {n} feature(s). Edits are NOT saved.")

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
