from qgis.utils import iface
from PyQt5.QtWidgets import QMessageBox
from qgis.core import QgsDistanceArea

# Get the active layer
layer = iface.activeLayer()

# Check if it's a valid vector layer
if layer is None or not layer.type() == layer.VectorLayer:
    QMessageBox.information(None, "Selection Info", "Please select a vector layer.")
else:
    selected_features = layer.selectedFeatures()
    count = len(selected_features)

    if count == 0:
        QMessageBox.information(None, "Selection Info", "No features selected.")
    else:
        # Setup QgsDistanceArea for accurate area measurement
        dist = QgsDistanceArea()
        dist.setSourceCrs(layer.crs(), iface.mapCanvas().mapSettings().transformContext())
        dist.setEllipsoid(layer.crs().ellipsoidAcronym() or 'WGS84')

        total_area = 0
        for feat in selected_features:
            geom = feat.geometry()
            if geom and geom.isGeosValid():
                total_area += dist.measureArea(geom)

        avg_area = total_area / count if count > 0 else 0

        # Round to integer and format
        message = f"Selected features: {count}\nAverage area: {int(avg_area)} m²"
        QMessageBox.information(None, "Selection Info", message)
