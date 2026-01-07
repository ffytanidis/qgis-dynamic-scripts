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

# Fast local bindings
to_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
to_4326 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform
hypot = math.hypot
ceil = math.ceil
Qpt = QgsPointXY

def ring_needs_densify_3857_pts(ring_pts, max_m):
    """Early-exit scan (assumes ring is valid/closed)."""
    if not ring_pts or len(ring_pts) < 2:
        return False

    p0 = ring_pts[0]
    x1, y1 = to_3857(p0.x(), p0.y())
    for p in ring_pts[1:]:
        x2, y2 = to_3857(p.x(), p.y())
        if hypot(x2 - x1, y2 - y1) > max_m:
            return True
        x1, y1 = x2, y2
    return False

def densify_ring_3857_pts(ring_pts, max_m):
    """
    Densify a closed ring (list of QgsPointXY).
    Returns (new_ring_pts, changed_bool).
    """
    npts = len(ring_pts)
    if npts < 2:
        return ring_pts, False

    out = []
    changed = False

    p_prev = ring_pts[0]
    lon1, lat1 = p_prev.x(), p_prev.y()
    X1, Y1 = to_3857(lon1, lat1)

    for p in ring_pts[1:]:
        lon2, lat2 = p.x(), p.y()
        X2, Y2 = to_3857(lon2, lat2)

        dX = X2 - X1
        dY = Y2 - Y1
        dist_m = hypot(dX, dY)

        nseg = max(1, int(ceil(dist_m / max_m)))
        if nseg > 1:
            changed = True

        # keep segment start
        out.append(Qpt(lon1, lat1))

        if nseg > 1:
            inv = 1.0 / nseg
            for i in range(1, nseg):
                xi = X1 + dX * (i * inv)
                yi = Y1 + dY * (i * inv)
                loni, lati = to_4326(xi, yi)
                out.append(Qpt(loni, lati))

        # advance
        lon1, lat1, X1, Y1 = lon2, lat2, X2, Y2

    # append last vertex
    out.append(Qpt(lon1, lat1))
    return out, changed

def densify_poly_or_mpoly_3857(geom, max_m):
    """Returns (new_geometry, changed_bool)."""
    if geom.isEmpty() or geom.type() != QgsWkbTypes.PolygonGeometry:
        return QgsGeometry(geom), False

    polys = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]

    # Early exit: if no ring needs densification, return original
    needs = False
    for poly in polys:
        if not poly:
            continue
        if ring_needs_densify_3857_pts(poly[0], max_m):
            needs = True
            break
        for hole in poly[1:]:
            if ring_needs_densify_3857_pts(hole, max_m):
                needs = True
                break
        if needs:
            break

    if not needs:
        return QgsGeometry(geom), False

    new_mp = []
    changed_any = False

    for poly in polys:
        if not poly:
            continue

        ext, ch_ext = densify_ring_3857_pts(poly[0], max_m)
        changed_any = changed_any or ch_ext

        holes = []
        for hole in poly[1:]:
            h, ch_h = densify_ring_3857_pts(hole, max_m)
            changed_any = changed_any or ch_h
            holes.append(h)

        new_mp.append([ext] + holes)

    return QgsGeometry.fromMultiPolygonXY(new_mp), changed_any

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
            "No features are selected.\n\nApply densification to ALL features of the active layer?",
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

    max_km, ok = QInputDialog.getDouble(
        iface.mainWindow(),
        "Mercator (EPSG:3857) densify polygons",
        f"{n} feature(s) will be densified.\n\nEnter maximum segment length (km) in EPSG:3857:",
        value=100.0,
        min=0.001,
        decimals=3
    )
    if not ok:
        msg_warn("Operation cancelled by user.")
        raise SystemExit

    max_m = max_km * 1000.0

    # Progress bar
    progress_msg = bar.createMessage("Densifying features…")
    progress = QProgressBar()
    progress.setRange(0, n)
    progress.setValue(0)
    progress_msg.layout().addWidget(progress)
    progress_handle = bar.pushWidget(progress_msg, Qgis.Info)

    changed = skipped = 0

    # Micro-optimization: localize hot callables
    set_prog = progress.setValue
    change_geom = layer.changeGeometry

    layer.beginEditCommand("Mercator densify polygons")
    try:
        it = layer.getFeatures() if apply_all else layer.getSelectedFeatures()
        for i, f in enumerate(it, start=1):
            g = f.geometry()
            if g.isEmpty() or g.type() != QgsWkbTypes.PolygonGeometry:
                skipped += 1
                set_prog(i)
                continue

            ng, did_change = densify_poly_or_mpoly_3857(g, max_m)
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
