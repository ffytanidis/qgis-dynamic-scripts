from qgis.utils import iface
from pyproj import Transformer
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices

# Get the center of the current map canvas
extent = iface.mapCanvas().extent()
center_x = (extent.xMinimum() + extent.xMaximum()) / 2
center_y = (extent.yMinimum() + extent.yMaximum()) / 2

# Transform from EPSG:3857 to EPSG:4326
transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
lon, lat = transformer.transform(center_x, center_y)

# Create the Google Maps URL
url = f"https://www.google.com/maps/place/{lat:.7f}+{lon:.7f}"

# Automatically open the URL in the default web browser
QDesktopServices.openUrl(QUrl(url))
