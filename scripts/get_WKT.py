from qgis.PyQt.QtWidgets import QMessageBox

layer = iface.activeLayer()
selected_features = layer.selectedFeatures()

if selected_features:
    geom = selected_features[0].geometry()
    wkt = geom.asWkt()
    QMessageBox.information(None, "Selected Geometry WKT", wkt)
else:
    QMessageBox.warning(None, "No Selection", "No features selected.")
