# Paste this into the QGIS Python Console
from qgis.PyQt import QtWidgets
from qgis.core import (
    QgsProject, QgsFeature, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsWkbTypes
)

def add_wkt_to_active_layer():
    layer = iface.activeLayer()
    if layer is None or layer.type() != layer.VectorLayer:
        QtWidgets.QMessageBox.warning(None, "Add WKT", "Select a vector layer first.")
        return

    if not layer.isEditable():
        QtWidgets.QMessageBox.warning(None, "Add WKT", "Make the selected layer editable and try again.")
        return

    text, ok = QtWidgets.QInputDialog.getMultiLineText(
        None, "Paste WKT", "Enter WKT (assumed EPSG:4326):", ""
    )
    if not ok or not text.strip():
        return

    wkt = text.strip()
    geom = QgsGeometry.fromWkt(wkt)
    if geom.isEmpty():
        QtWidgets.QMessageBox.critical(None, "Add WKT", "Could not parse geometry from the provided WKT.")
        return

    # Always assume input WKT is in EPSG:4326
    src_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    layer_crs = layer.crs()

    # Transform if the layer CRS is different
    if src_crs != layer_crs:
        try:
            xform = QgsCoordinateTransform(src_crs, layer_crs, QgsProject.instance())
            geom.transform(xform)
        except Exception as e:
            QtWidgets.QMessageBox.critical(None, "Add WKT", f"Reprojection failed:\n{e}")
            return

    # Check geometry type
    if QgsWkbTypes.geometryType(geom.wkbType()) != layer.geometryType():
        gt_names = {0: "Point", 1: "Line", 2: "Polygon"}
        need = gt_names.get(layer.geometryType(), "Unknown")
        got = gt_names.get(QgsWkbTypes.geometryType(geom.wkbType()), "Unknown")
        QtWidgets.QMessageBox.critical(None, "Add WKT",
            f"Geometry type mismatch.\nLayer expects: {need}\nProvided WKT: {got}")
        return

    # Convert to Multi* if layer is Multi*
    if QgsWkbTypes.isMultiType(layer.wkbType()) and not QgsWkbTypes.isMultiType(geom.wkbType()):
        geom = QgsGeometry.fromWkt(f"MULTI{geom.asWkt()}")

    feat = QgsFeature(layer.fields())
    feat.setGeometry(geom)

    # Add feature to the edit buffer
    layer.beginEditCommand("Add WKT feature")
    if layer.addFeature(feat):
        layer.endEditCommand()
        try:
            layer.removeSelection()
            layer.select(feat.id())
            iface.mapCanvas().zoomToSelected(layer)
        except Exception:
            pass
        layer.triggerRepaint()
        QtWidgets.QMessageBox.information(None, "Add WKT", "Feature added to edit buffer.")
    else:
        layer.destroyEditCommand()
        QtWidgets.QMessageBox.critical(None, "Add WKT", "Failed to add feature. Check constraints or geometry.")

add_wkt_to_active_layer()
