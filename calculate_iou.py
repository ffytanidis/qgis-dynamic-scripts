from qgis.core import QgsProject, QgsVectorLayer, QgsGeometry
from qgis.utils import iface
from PyQt5.QtWidgets import QMessageBox

# Collect selected geometries from all vector layers
selected_features = []
for layer in QgsProject.instance().mapLayers().values():
    if isinstance(layer, QgsVectorLayer) and layer.selectedFeatureCount() > 0:
        for feature in layer.selectedFeatures():
            selected_features.append((layer.name(), feature.geometry()))

# Ensure at least two features from different layers
if len(selected_features) < 2:
    QMessageBox.warning(iface.mainWindow(), "Intersection over Union",
                        "Select at least two features from different layers.")
else:
    # Find overlapping features from different layers
    iou_values = []
    for i in range(len(selected_features)):
        name_i, geom_i = selected_features[i]
        for j in range(i + 1, len(selected_features)):
            name_j, geom_j = selected_features[j]
            if name_i != name_j and geom_i.intersects(geom_j):
                intersection = geom_i.intersection(geom_j)
                union = geom_i.combine(geom_j)
                if not intersection.isEmpty() and not union.isEmpty():
                    inter_area = intersection.area()
                    union_area = union.area()
                    iou = inter_area / union_area if union_area != 0 else 0
                    iou_values.append((name_i, name_j, iou))

    # Show results
    if iou_values:
        result = "\n".join([f"{a} ∩ {b} / {a} ∪ {b} = {iou:.4f}" for a, b, iou in iou_values])
        QMessageBox.information(iface.mainWindow(), "Intersection over Union", result)
    else:
        QMessageBox.information(iface.mainWindow(), "Intersection over Union", "No overlapping features found.")
