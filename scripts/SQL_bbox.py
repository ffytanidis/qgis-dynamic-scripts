from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.utils import iface
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QApplication
from PyQt5.QtGui import QClipboard
from PyQt5.QtCore import Qt

# get canvas and extent
canvas = iface.mapCanvas()
extent = canvas.extent()
crs_canvas = canvas.mapSettings().destinationCrs()

# if CRS is not WGS84, transform to EPSG:4326
if crs_canvas.authid() != 'EPSG:4326':
    crs_dest = QgsCoordinateReferenceSystem('EPSG:4326')
    xform = QgsCoordinateTransform(crs_canvas, crs_dest, QgsProject.instance())
    bottom_left = xform.transform(extent.xMinimum(), extent.yMinimum())
    top_right = xform.transform(extent.xMaximum(), extent.yMaximum())
    min_lon, min_lat = bottom_left.x(), bottom_left.y()
    max_lon, max_lat = top_right.x(), top_right.y()
else:
    # already in EPSG:4326
    min_lon, max_lon = extent.xMinimum(), extent.xMaximum()
    min_lat, max_lat = extent.yMinimum(), extent.yMaximum()

# format SQL clause
sql_clause = (
    f"where ps.LON between {min_lon:.7f} and {max_lon:.7f} "
    f"and ps.LAT between {min_lat:.7f} and {max_lat:.7f}"
)

# custom dialog with copy functionality
dialog = QDialog()
dialog.setWindowTitle("Visible Extent as SQL")

layout = QVBoxLayout()

label = QLabel(sql_clause)
label.setTextInteractionFlags(Qt.TextSelectableByMouse)
layout.addWidget(label)

# buttons
button_layout = QHBoxLayout()
copy_button = QPushButton("Copy")
ok_button = QPushButton("OK")

button_layout.addWidget(copy_button)
button_layout.addWidget(ok_button)
layout.addLayout(button_layout)

dialog.setLayout(layout)

# connect buttons
def copy_and_close():
    QApplication.clipboard().setText(sql_clause)
    dialog.accept()

copy_button.clicked.connect(copy_and_close)
ok_button.clicked.connect(dialog.accept)

dialog.exec_()
