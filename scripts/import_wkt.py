# Paste this into the QGIS Python Console
from qgis.PyQt import QtWidgets
from qgis.core import (
    QgsProject, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsWkbTypes
)

def replace_selected_geom_with_wkt():
    layer = iface.activeLayer()
    if layer is None or layer.type() != layer.VectorLayer:
        QtWidgets.QMessageBox.warning(None, "WKT → Selection", "Select a vector layer first.")
        return

    if not layer.isEditable():
        QtWidgets.QMessageBox.warning(None, "WKT → Selection", "Make the selected layer editable and try again.")
        return

    sel = layer.selectedFeatureIds()
    if len(sel) != 1:
        QtWidgets.QMessageBox.warning(None, "WKT → Selection", "Select exactly one feature to replace its geometry.")
        return
    fid = sel[0]

    text, ok = QtWidgets.QInputDialog.getMultiLineText(
        None, "Paste WKT", "Enter WKT (assumed EPSG:4326):", ""
    )
    if not ok or not text.strip():
        return

    wkt = text.strip()
    geom = QgsGeometry.fromWkt(wkt)
    if geom.isNull() or geom.isEmpty():
        QtWidgets.QMessageBox.critical(None, "WKT → Selection", "Could not parse geometry from the provided WKT.")
        return

    # Assume input WKT is in EPSG:4326 and reproject to layer CRS if needed
    src_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    dst_crs = layer.crs()
    if src_crs != dst_crs:
        try:
            xform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
            geom.transform(xform)
        except Exception as e:
            QtWidgets.QMessageBox.critical(None, "WKT → Selection", f"Reprojection failed:\n{e}")
            return

    # Basic geometry type guard (Point/Line/Polygon)
    if QgsWkbTypes.geometryType(geom.wkbType()) != layer.geometryType():
        gt_names = {QgsWkbTypes.PointGeometry: "Point",
                    QgsWkbTypes.LineGeometry: "Line",
                    QgsWkbTypes.PolygonGeometry: "Polygon"}
        need = gt_names.get(layer.geometryType(), "Unknown")
        got = gt_names.get(QgsWkbTypes.geometryType(geom.wkbType()), "Unknown")
        QtWidgets.QMessageBox.critical(None, "WKT → Selection",
            f"Geometry type mismatch.\nLayer expects: {need}\nProvided WKT: {got}")
        return

    # Upgrade single → multi if layer is multi
    if QgsWkbTypes.isMultiType(layer.wkbType()) and not QgsWkbTypes.isMultiType(geom.wkbType()):
        geom = QgsGeometry.fromWkt(f"MULTI{geom.asWkt()}")

    # Apply the change in the edit buffer (no auto-save)
    layer.beginEditCommand("Replace geometry from WKT")
    if layer.changeGeometry(fid, geom):
        layer.endEditCommand()
        try:
            # Keep selection; refresh map to show the new geometry
            iface.mapCanvas().refresh()
        except Exception:
            pass
        QtWidgets.QMessageBox.information(
            None, "WKT → Selection",
            "Selected feature's geometry replaced in the edit buffer."
        )
    else:
        layer.destroyEditCommand()
        QtWidgets.QMessageBox.critical(None, "WKT → Selection",
            "Failed to change geometry. Check constraints or geometry validity.")

# Run it
replace_selected_geom_with_wkt()
