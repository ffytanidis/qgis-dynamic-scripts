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

# custom dialog
class SQLDialog(QDialog):
    def __init__(self, sql_text):
        super().__init__()
        self.setWindowTitle("Visible Extent as SQL")
        self.setModal(True)
        layout = QVBoxLayout()

        self.label = QLabel(sql_text)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.label)

        btn_layout = QHBoxLayout()
        self.copy_button = QPushButton("Copy")
        self.ok_button = QPushButton("OK")
        btn_layout.addWidget(self.copy_button)
        btn_layout.addWidget(self.ok_button)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

        # connect buttons
        self.copy_button.clicked.connect(self.copy_and_close)
        self.ok_button.clicked.connect(self.close)

    def copy_and_close(self):
        QApplication.clipboard().setText(self.label.text())
        self.close()  # force close instead of accept()

# show dialog
dialog = SQLDialog(sql_clause)
dialog.show()
