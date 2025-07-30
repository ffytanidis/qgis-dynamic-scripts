import math
from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsGeometry,
)

# Prepare the transformation: from EPSG:4326 (WGS 84) to EPSG:3857 (Web Mercator)
source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
target_crs = QgsCoordinateReferenceSystem("EPSG:3857")
transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())

# Get the active layer
layer = iface.activeLayer()
if not layer:
    print("No active layer found!")
    exit()

# Get the selected features
features = layer.selectedFeatures()
if not features:
    print("No features selected!")
    exit()

layer.startEditing()  # Enable editing mode
for feature in features:
    geom = feature.geometry()
    if not geom:
        print(f"Feature {feature.id()} has no geometry.")
        continue

    # Ensure the geometry is in the projected CRS for accurate area calculation
    geom_proj = geom
    geom.transform(transform)  # Transform geometry to target CRS (e.g., EPSG:3857)

    # Calculate the radius that will give us the desired area for the octagon
    radius = math.sqrt(geom_proj.area() / (2 * math.sqrt(2)))


    # Generate octagon points in EPSG:3857 using the calculated radius
    centroid_proj = geom_proj.centroid().asPoint()  # Centroid in projected CRS
    angles = [0, 45, 90, 135, 180, 225, 270, 315]  # Degrees for vertices
    octagon_points_proj = [
        QgsPointXY(
            centroid_proj.x() + radius * math.cos(math.radians(angle)),
            centroid_proj.y() + radius * math.sin(math.radians(angle))
        )
        for angle in angles
    ]

    # Transform octagon points back to EPSG:4326
    octagon_points = [transform.transform(point, QgsCoordinateTransform.ReverseTransform) for point in octagon_points_proj]

    # Create the octagon geometry
    octagon = QgsGeometry.fromPolygonXY([[QgsPointXY(pt.x(), pt.y()) for pt in octagon_points]])  # Build polygon
    layer.changeGeometry(feature.id(), octagon)  # Replace geometry


print("Octagon transformation completed with corrected area in meters.")
