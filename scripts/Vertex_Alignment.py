import math
import processing
from qgis.PyQt.QtWidgets import QInputDialog, QProgressBar, QMessageBox
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsWkbTypes, QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsFeature, QgsRectangle,
    QgsVectorLayer, QgsField, QgsFields, Qgis
)
from qgis.utils import iface

bar = iface.messageBar()

def _msg(title, text, level, duration):
    bar.pushMessage(title, text, level=level, duration=duration)

msg_ok   = lambda t, d=5: _msg("Success", t, Qgis.Success, d)
msg_warn = lambda t, d=6: _msg("Warning", t, Qgis.Warning, d)
msg_err  = lambda t, d=8: _msg("Error",   t, Qgis.Critical, d)

# ---- settings ----
DECIMALS = 6
EPS = 1e-12

def r4(v): return round(v, DECIMALS)

def rect_expand(xmin, ymin, xmax, ymax, tol):
    return QgsRectangle(xmin - tol, ymin - tol, xmax + tol, ymax + tol)

def seg_bbox(p1, p2):
    x1, y1 = p1.x(), p1.y()
    x2, y2 = p2.x(), p2.y()
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

def closest_point_on_segment(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    denom = dx*dx + dy*dy
    if denom <= 0.0:
        return ax, ay, 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    if t <= 0.0:
        return ax, ay, 0.0
    if t >= 1.0:
        return bx, by, 1.0
    return (ax + t*dx, ay + t*dy, t)

def ring_is_closed(r):
    return bool(r) and r[0] == r[-1]

def ensure_closed(r):
    return r if ring_is_closed(r) else (r + [r[0]] if r else r)

def ring_vertices_set(ring):
    return {(r4(p.x()), r4(p.y())) for p in ring}

def count_segments_in_geom(g):
    if g.isEmpty() or g.type() != QgsWkbTypes.PolygonGeometry:
        return 0
    polys = g.asMultiPolygon() if g.isMultipart() else [g.asPolygon()]
    s = 0
    for poly in polys:
        if not poly:
            continue
        for ring in poly:
            ring = ensure_closed(ring)
            if len(ring) >= 2:
                s += (len(ring) - 1)
    return s

def collect_target_vertices(ids, geoms_by_id, tol_bar=None):
    """
    Target = all vertices rounded to 4 decimals + deduplicated.
    Returns: (target_index, id_to_xy, n_targets)
    """
    idx = QgsSpatialIndex()
    id_to_xy = {}
    seen = set()
    fid = 1

    # Optional progress updates
    done = 0
    UI_EVERY = 2000

    for gid in ids:
        g = geoms_by_id[gid]
        for v in g.vertices():
            xy = (r4(v.x()), r4(v.y()))
            if xy in seen:
                continue
            seen.add(xy)
            f = QgsFeature()
            f.setId(fid)
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*xy)))
            idx.addFeature(f)
            id_to_xy[fid] = xy
            fid += 1

        done += 1
        if tol_bar and (done % max(1, UI_EVERY // 100) == 0):
            tol_bar.setValue(done)

    if tol_bar:
        tol_bar.setValue(len(ids))
    return idx, id_to_xy, len(seen)

def node_ring_to_targets(ring, tol, target_index, id_to_xy):
    ring = ensure_closed(ring)
    n = len(ring)
    if n < 2:
        return ring, False

    vset = ring_vertices_set(ring)
    inserts_by_seg = {}

    for i in range(n - 1):
        p1 = ring[i]
        p2 = ring[i + 1]
        xmin, ymin, xmax, ymax = seg_bbox(p1, p2)
        cand_ids = target_index.intersects(rect_expand(xmin, ymin, xmax, ymax, tol))
        if not cand_ids:
            continue

        ax, ay = p1.x(), p1.y()
        bx, by = p2.x(), p2.y()

        seg_inserts = []
        for cid in cand_ids:
            tx, ty = id_to_xy[cid]
            qx, qy, t = closest_point_on_segment(tx, ty, ax, ay, bx, by)
            dx = tx - qx
            dy = ty - qy
            if (dx*dx + dy*dy) > (tol * tol):
                continue
            if t <= EPS or t >= 1.0 - EPS:
                continue
            key = (r4(qx), r4(qy))
            if key in vset:
                continue
            seg_inserts.append((t, qx, qy))

        if seg_inserts:
            seen_seg = set()
            uniq = []
            for t, qx, qy in sorted(seg_inserts, key=lambda z: z[0]):
                key = (r4(qx), r4(qy))
                if key in seen_seg:
                    continue
                seen_seg.add(key)
                uniq.append((t, qx, qy))
            inserts_by_seg[i] = uniq

    if not inserts_by_seg:
        return ring, False

    out = []
    changed = False
    for i in range(n - 1):
        out.append(ring[i])
        if i in inserts_by_seg:
            for _, qx, qy in inserts_by_seg[i]:
                out.append(QgsPointXY(qx, qy))
                vset.add((r4(qx), r4(qy)))
                changed = True
    out.append(ring[-1])
    return ensure_closed(out), changed

def make_point_layer_from_targets(id_to_xy):
    vl = QgsVectorLayer("Point?crs=EPSG:4326", "snap_targets", "memory")
    dp = vl.dataProvider()
    dp.addAttributes([QgsField("id", QVariant.Int)])
    vl.updateFields()

    feats = []
    for pid, (x, y) in id_to_xy.items():
        f = QgsFeature(vl.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        f.setAttributes([int(pid)])
        feats.append(f)

    dp.addFeatures(feats)
    vl.updateExtents()
    return vl

def make_work_poly_layer(layer, ids, geoms_by_id):
    geom_str = QgsWkbTypes.displayString(layer.wkbType())
    vl = QgsVectorLayer(f"{geom_str}?crs=EPSG:4326", "snap_input", "memory")
    dp = vl.dataProvider()
    dp.addAttributes([QgsField("__orig_id", QVariant.LongLong)])
    vl.updateFields()

    feats = []
    for fid in ids:
        f = QgsFeature(vl.fields())
        f.setGeometry(geoms_by_id[fid])
        f.setAttributes([int(fid)])
        feats.append(f)

    dp.addFeatures(feats)
    vl.updateExtents()
    return vl

def push_stage_progress(stage_i, stage_n, label, maximum):
    msg = bar.createMessage(f"Stage {stage_i}/{stage_n}: {label}")
    pb = QProgressBar()
    pb.setRange(0, maximum)
    pb.setValue(0)
    msg.layout().addWidget(pb)
    handle = bar.pushWidget(msg, Qgis.Info)
    return handle, pb

# ---- MAIN ----
handles = []  # store progress widgets so we can pop them at the end

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
            "No features are selected.\n\nApply operation to ALL features of the active layer?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ans != QMessageBox.Yes:
            msg_warn("Operation cancelled.")
            raise SystemExit
        apply_all = True

    it = layer.getFeatures() if apply_all else layer.getSelectedFeatures()

    ids = []
    geoms = {}
    skipped = 0
    for f in it:
        g = f.geometry()
        if (not g) or g.isEmpty() or g.type() != QgsWkbTypes.PolygonGeometry:
            skipped += 1
            continue
        ids.append(f.id())
        geoms[f.id()] = QgsGeometry(g)

    if len(ids) < 2:
        msg_warn("Need at least 2 polygon features (selection or layer) to run.")
        raise SystemExit

    tol_deg, ok = QInputDialog.getDouble(
        iface.mainWindow(),
        "Node edges then snap to vertices",
        f"{len(ids)} feature(s) will be processed.\n\nEnter distance tolerance (degrees):",
        value=0.0001,
        min=0.0,
        decimals=10
    )
    if not ok:
        msg_warn("Operation cancelled by user.")
        raise SystemExit
    if tol_deg <= 0.0:
        msg_warn("Tolerance is 0. No changes were made.")
        raise SystemExit

    STAGES = 3

    # ---- Stage 1: Build target vertex collection (rounded+dedup + spatial index) ----
    h1, pb1 = push_stage_progress(1, STAGES, "Build target vertices (4 decimals, dedup)", maximum=len(ids))
    handles.append(h1)

    target_index, id_to_xy, n_targets = collect_target_vertices(ids, geoms, tol_bar=pb1)
    pb1.setValue(len(ids))

    # ---- Stage 2: Node edges near target vertices ----
    total_segments = sum(count_segments_in_geom(geoms[fid]) for fid in ids)
    if total_segments <= 0:
        msg_warn("No segments found to process.")
        raise SystemExit

    h2, pb2 = push_stage_progress(2, STAGES, "Node edges near target vertices", maximum=total_segments)
    handles.append(h2)

    UI_EVERY = 500
    seg_done = 0
    touched = set()

    for fid in ids:
        g = geoms[fid]
        polys = g.asMultiPolygon() if g.isMultipart() else [g.asPolygon()]
        new_mp = []
        changed_any = False

        for poly in polys:
            if not poly:
                continue

            ring = ensure_closed(poly[0])
            new_ring, ch = node_ring_to_targets(ring, tol_deg, target_index, id_to_xy)
            changed_any |= ch
            seg_done += max(0, len(ring) - 1)

            holes = []
            for h in poly[1:]:
                hr = ensure_closed(h)
                new_h, chh = node_ring_to_targets(hr, tol_deg, target_index, id_to_xy)
                changed_any |= chh
                seg_done += max(0, len(hr) - 1)
                holes.append(new_h)

            new_mp.append([new_ring] + holes)

            if seg_done % UI_EVERY == 0:
                pb2.setValue(min(seg_done, total_segments))

        if changed_any:
            geoms[fid] = QgsGeometry.fromMultiPolygonXY(new_mp)
            touched.add(fid)

    pb2.setValue(total_segments)

    # Apply noding edits (only touched)
    if touched:
        layer.beginEditCommand("Node edges near target vertices (EPSG:4326)")
        try:
            for fid in touched:
                layer.changeGeometry(fid, geoms[fid])
        finally:
            layer.endEditCommand()
            layer.triggerRepaint()

    # ---- Stage 3: Snap to target vertices (Processing) ----
    h3, pb3 = push_stage_progress(3, STAGES, "Snap geometries to target vertices", maximum=len(ids))
    handles.append(h3)

    ref_pts = make_point_layer_from_targets(id_to_xy)
    in_polys = make_work_poly_layer(layer, ids, geoms)

    out = processing.run(
        "native:snapgeometries",
        {
            "INPUT": in_polys,
            "REFERENCE_LAYER": ref_pts,
            "TOLERANCE": float(tol_deg),
            "BEHAVIOR": 0,
            "OUTPUT": "memory:"
        }
    )["OUTPUT"]

    idx = out.fields().indexOf("__orig_id")
    if idx < 0:
        msg_err("Internal error: __orig_id missing in snap output.")
        raise SystemExit

    changed_snap = 0
    layer.beginEditCommand("Snap to target vertices (EPSG:4326)")
    try:
        for i, f in enumerate(out.getFeatures(), start=1):
            fid = int(f.attributes()[idx])
            og = f.geometry()
            if og and not og.isEmpty():
                layer.changeGeometry(fid, og)
                changed_snap += 1
            pb3.setValue(i)
    finally:
        layer.endEditCommand()
        layer.triggerRepaint()

    pb3.setValue(len(ids))

    msg_ok(
        f"Finished. Targets: {n_targets}. "
        f"Noded features: {len(touched)}. Snapped features: {changed_snap}. "
        f"Skipped: {skipped}. Edits are NOT saved."
    )

except SystemExit:
    pass
except Exception as e:
    msg_err(f"Unexpected error: {e}")
finally:
    # keep the progress bars visible briefly? (we'll remove immediately to keep clean)
    for h in handles:
        try:
            bar.popWidget(h)
        except Exception:
            pass

