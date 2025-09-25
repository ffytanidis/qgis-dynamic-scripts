# pyqgis: replace selected polygon geometries with equal-area regular octagons
# - messages via iface.messageBar()
# - no exit(), no commit/rollback (you decide to save edits)
# - transforms layer crs -> epsg:3857 for metric area, then back

import math
from qgis.PyQt import QtWidgets
from qgis.core import (
    Qgis,
    QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsPointXY, QgsGeometry, QgsWkbTypes
)

def show_msg(text, level=Qgis.Info, duration=10):
    iface.messageBar().pushMessage("octagon tool", text, level=level, duration=duration)

# get active layer
layer = iface.activeLayer()
if not layer:
    show_msg("no active layer", Qgis.Warning, 10)
elif not layer.selectedFeatureCount():
    show_msg("no selected features", Qgis.Warning, 10)
else:
    # only meaningful for polygon geometry
    if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
        show_msg("layer is not polygon geometry", Qgis.Warning, 10)
    else:
        # prepare transforms (source = layer crs, working = epsg:3857)
        src_crs = layer.crs()
        m_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        to_m = QgsCoordinateTransform(src_crs, m_crs, QgsProject.instance())
        to_src = QgsCoordinateTransform(m_crs, src_crs, QgsProject.instance())

        layer.startEditing()
        changed = 0
        skipped_empty = 0
        skipped_nonfinite = 0

        for f in layer.selectedFeatures():
            g = f.geometry()
            if not g or g.isEmpty():
                skipped_empty += 1
                continue

            g_m = QgsGeometry(g)  # copy
            g_m.transform(to_m)  # work in meters

            area = g_m.area()
            if not math.isfinite(area) or area <= 0:
                skipped_nonfinite += 1
                continue

            # compute circumradius R so that regular octagon area matches polygon area
            # area_octagon = 2 * sqrt(2) * R^2  ->  R = sqrt(area / (2*sqrt(2)))
            R = math.sqrt(area / (2.0 * math.sqrt(2.0)))

            # centroid in metric crs
            c = g_m.centroid().asPoint()
            angles = (0, 45, 90, 135, 180, 225, 270, 315)
            verts_m = [
                QgsPointXY(
                    c.x() + R * math.cos(math.radians(a)),
                    c.y() + R * math.sin(math.radians(a))
                ) for a in angles
            ]

            # build polygon in metric, then back to source crs
            oct_m = QgsGeometry.fromPolygonXY([verts_m])
            oct_src = QgsGeometry(oct_m)  # copy to transform back
            oct_src.transform(to_src)

            layer.changeGeometry(f.id(), oct_src)
            changed += 1

        if changed > 0:
            msg = f"replaced {changed} feature(s) with equal-area octagons"
            if skipped_empty or skipped_nonfinite:
                msg += f" (skipped empty={skipped_empty}, invalid/zero-area={skipped_nonfinite})"
            show_msg(msg, Qgis.Success, 10)
        else:
            if skipped_empty or skipped_nonfinite:
                show_msg(f"no geometry updated (skipped empty={skipped_empty}, invalid/zero-area={skipped_nonfinite})", Qgis.Info, 10)
            else:
                show_msg("no geometry updated", Qgis.Info, 10)
