import math
from pyproj import Geod
from qgis.PyQt.QtWidgets import QInputDialog, QProgressBar
from qgis.core import QgsWkbTypes, QgsGeometry, QgsPointXY, Qgis
from qgis.utils import iface

GEOD = Geod(ellps="WGS84")
bar = iface.messageBar()

def msg_ok(text, duration=5):
    bar.pushMessage("Success", text, level=Qgis.Success, duration=duration)

def msg_warn(text, duration=6):
    bar.pushMessage("Warning", text, level=Qgis.Warning, duration=duration)

def msg_err(text, duration=8):
    bar.pushMessage("Error", text, level=Qgis.Critical, duration=duration)

def ensure_closed_xy(ring):
    return ring if ring and ring[0] == ring[-1] else ring + [ring[0]]

def densify_segment_geodesic(p1, p2, max_km):
    lon1, lat1 = p1.x(), p1.y()
    lon2, lat2 = p2.x(), p2.y()
    _, _, dist_m = GEOD.inv(lon1, lat1, lon2, lat2)
    dist_km = dist_m / 1000.0
    n = max(0, int(math.ceil(dist_km / max_km)) - 1)
    if n <= 0:
        return []
    pts = GEOD.npts(lon1, lat1, lon2, lat2, n)
    return [QgsPointXY(lon, lat) for lon, lat in pts]

def densify_ring_geodesic(ring, max_km):
    ring = ensure_closed_xy(ring)
    if len(ring) < 2:
        return ring
    out = []
    for i in range(len(ring) - 1):
        p1 = ring[i]
        p2 = ring[i + 1]
        out.append(p1)
        out.extend(densify_segment_geodesic(p1, p2, max_km))
    out.append(ring[-1])
    return ensure_closed_xy(out)

def densify_polygon_or_multipolygon(geom, max_km):
    if geom.isEmpty() or geom.type() != QgsWkbTypes.PolygonGeometry:
        return QgsGeometry(geom)
    mp = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
    new_mp = []
    for poly in mp:
        if not poly:
            continue
        ext = densify_ring_geodesic(poly[0], max_km)
        holes = [densify_ring_geodesic(r, max_km) for r in poly[1:]]
        new_mp.append([ext] + holes)
    return QgsGeometry.fromMultiPolygonXY(new_mp)

# ---- MAIN (crash-safe) ----
progress_handle = None

try:
    layer = iface.activeLayer()
    if layer is None:
        msg_err("No active layer selected.")
    elif layer.crs().authid() != "EPSG:4326":
        msg_err(f"Layer CRS is {layer.crs().authid()}, expected EPSG:4326.")
    elif not layer.isEditable():
        # IMPORTANT: do NOT raise/exit hard; just warn and return
        msg_warn("Layer is not in edit mode. Enable editing and re-run.")
    else:
        feats = list(layer.selectedFeatures())
        n_feats = len(feats)
        if n_feats == 0:
            msg_warn("No selected features.")
        else:
            # Input
            prompt = f"{n_feats} selected feature(s) will be densified.\n\nEnter maximum segment length (km):"
            max_km, ok = QInputDialog.getDouble(
                iface.mainWindow(),
                "Geodesic densify polygons",
                prompt,
                value=40.0,
                min=0.001,
                decimals=3
            )
            if not ok:
                msg_warn("Operation cancelled by user.")
            else:
                # Progress bar (only created after all preconditions pass)
                progress_msg = bar.createMessage("Densifying selected features…")
                progress = QProgressBar()
                progress.setMinimum(0)
                progress.setMaximum(n_feats)
                progress.setValue(0)
                progress_msg.layout().addWidget(progress)
                progress_handle = bar.pushWidget(progress_msg, Qgis.Info)

                changed = 0
                skipped = 0

                layer.beginEditCommand("Geodesic densify selected polygons")
                try:
                    for i, f in enumerate(feats, start=1):
                        g = f.geometry()
                        if g.isEmpty() or g.type() != QgsWkbTypes.PolygonGeometry:
                            skipped += 1
                        else:
                            new_g = densify_polygon_or_multipolygon(g, max_km)
                            if not new_g.equals(g):
                                layer.changeGeometry(f.id(), new_g)
                                changed += 1
                        progress.setValue(i)
                finally:
                    layer.endEditCommand()
                    layer.triggerRepaint()

                if changed == 0 and skipped == 0:
                    msg_warn("Finished. No geometry changes were necessary.")
                elif changed == 0:
                    msg_warn(f"Finished. No geometries changed. Skipped {skipped} feature(s).")
                else:
                    msg_ok(f"Finished. Modified {changed} of {n_feats} selected feature(s). Edits are NOT saved.")

except Exception as e:
    # If anything unexpected happens, report it instead of crashing QGIS
    msg_err(f"Unexpected error: {e}")

finally:
    # Always remove the progress widget if it was created
    if progress_handle is not None:
        try:
            bar.popWidget(progress_handle)
        except Exception:
            pass
