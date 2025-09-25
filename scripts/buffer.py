import math
from qgis.PyQt import QtWidgets
from qgis.core import (
    Qgis,
    QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry
)

def show_msg(text, level=Qgis.Info, duration=10):
    """helper to show message bar in qgis"""
    iface.messageBar().pushMessage("buffer tool", text, level=level, duration=duration)

# get active layer
layer = iface.activeLayer()
if not layer:
    show_msg("no active layer", Qgis.Warning, 10)
elif not layer.selectedFeatureCount():
    show_msg("no selected features", Qgis.Warning, 10)
else:
    # ask distance
    dist, ok = QtWidgets.QInputDialog.getDouble(
        iface.mainWindow(), "buffer (m)", "distance (negative allowed):",
        1000.0, -1e7, 1e7, 2
    )
    if not ok or not math.isfinite(dist):
        show_msg("given buffer not valid", Qgis.Warning, 10)
    else:
        # prepare transforms
        src = layer.crs()
        crs3857 = QgsCoordinateReferenceSystem("EPSG:3857")
        to3857 = QgsCoordinateTransform(src, crs3857, QgsProject.instance())
        to_src = QgsCoordinateTransform(crs3857, src, QgsProject.instance())

        # start editing + update selected geometries
        layer.startEditing()
        changed = 0
        for f in layer.selectedFeatures():
            g = f.geometry()
            if g and not g.isEmpty():
                g.transform(to3857)
                g_buf = g.buffer(dist, 1, QgsGeometry.CapRound, QgsGeometry.JoinStyleMiter, 5)
                g_buf.transform(to_src)
                layer.changeGeometry(f.id(), g_buf)
                changed += 1

        if changed > 0:
            show_msg(f"buffered {changed} feature(s) by {dist} m", Qgis.Success, 10)
        else:
            show_msg("no geometry updated", Qgis.Info, 10)
