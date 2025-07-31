# QGIS script to run parameterized SQL query on MSSQL connection and export result to CSV

from qgis.PyQt.QtWidgets import QDialog, QFormLayout, QLineEdit, QPushButton, QVBoxLayout, QFileDialog, QLabel, QCheckBox, QHBoxLayout, QApplication, QMessageBox
from qgis.PyQt.QtCore import QSettings
from qgis.core import QgsProviderRegistry, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.utils import iface
import csv
import os
import sys

# Get current canvas extent in EPSG:4326
canvas = iface.mapCanvas()
extent = canvas.extent()
crs_canvas = canvas.mapSettings().destinationCrs()
if crs_canvas.authid() != 'EPSG:4326':
    crs_dest = QgsCoordinateReferenceSystem('EPSG:4326')
    xform = QgsCoordinateTransform(crs_canvas, crs_dest, QgsProject.instance())
    bottom_left = xform.transform(extent.xMinimum(), extent.yMinimum())
    top_right = xform.transform(extent.xMaximum(), extent.yMaximum())
    min_lon, min_lat = bottom_left.x(), bottom_left.y()
    max_lon, max_lat = top_right.x(), top_right.y()
else:
    min_lon, max_lon = extent.xMinimum(), extent.xMaximum()
    min_lat, max_lat = extent.yMinimum(), extent.yMaximum()

# Define input dialog
class InputDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MSSQL Query Exporter")
        self.settings = QSettings()

        self.conn_name_input = QLineEdit(self.settings.value("conn_name", ""))
        self.folder_path_input = QLineEdit(self.settings.value("folder_path", ""))
        self.output_file_input = QLineEdit(self.settings.value("output_file", "output.csv"))
        self.speed_from_input = QLineEdit(self.settings.value("speed_from", "0"))
        self.speed_to_input = QLineEdit(self.settings.value("speed_to", "0"))
        self.timestamp_start_input = QLineEdit(self.settings.value("timestamp_start", "2023-07-20 00:00"))
        self.timestamp_end_input = QLineEdit(self.settings.value("timestamp_end", "2023-07-20 00:00"))
        self.only_imo_checkbox = QCheckBox("Only Having IMO")
        self.only_imo_checkbox.setChecked(self.settings.value("only_having_imo", "true") == "true")

        self.select_button = QPushButton("Change Folder")
        self.select_button.clicked.connect(self.select_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.folder_path_input)
        folder_layout.addWidget(self.select_button)

        layout = QFormLayout()
        layout.addRow("Connection Name:", self.conn_name_input)
        layout.addRow(QLabel("Output Folder:"))
        layout.addRow(folder_layout)
        layout.addRow("Output File Name:", self.output_file_input)
        layout.addRow("Speed From:", self.speed_from_input)
        layout.addRow("Speed To:", self.speed_to_input)
        layout.addRow("Timestamp Start:", self.timestamp_start_input)
        layout.addRow("Timestamp End:", self.timestamp_end_input)
        layout.addRow(self.only_imo_checkbox)

        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.run_button)
        btn_layout.addWidget(self.cancel_button)

        main_layout = QVBoxLayout()
        main_layout.addLayout(layout)
        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.folder_path_input.setText(folder)

    def get_values(self):
        return {
            "conn_name": self.conn_name_input.text(),
            "folder_path": self.folder_path_input.text(),
            "output_file": self.output_file_input.text(),
            "speed_from": self.speed_from_input.text(),
            "speed_to": self.speed_to_input.text(),
            "timestamp_start": self.timestamp_start_input.text(),
            "timestamp_end": self.timestamp_end_input.text(),
            "only_having_imo": self.only_imo_checkbox.isChecked()
        }

# Run dialog
app = QApplication.instance() or QApplication(sys.argv)
dialog = InputDialog()
if not dialog.exec_():
    raise Exception("Cancelled by user")

values = dialog.get_values()
settings = QSettings()
for key, val in values.items():
    settings.setValue(key, str(val))

conn_name = values["conn_name"]
folder = values["folder_path"]
output_file = values["output_file"]
speed_from = values["speed_from"]
speed_to = values["speed_to"]
timestamp_start = values["timestamp_start"]
timestamp_end = values["timestamp_end"]
only_having_imo = values["only_having_imo"]

# Construct SQL
sql = f"""
select ps.*, s.shipname, s.IMO, s.comfleet_groupedtype, s.type_summary, s.type_name, s.GRT, s.DWT,
    'https://www.marinetraffic.com/en/ais/details/ships/shipid:' + CAST(ps.SHIP_ID AS VARCHAR) as mt_link
from (
    select SHIP_ID, LON, LAT, TIMESTAMP, SPEED, COURSE, HEADING from [ais_archive_2022A].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, TIMESTAMP, SPEED, COURSE, HEADING from [ais_archive_2022B].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, TIMESTAMP, SPEED, COURSE, HEADING from [ais_archive_2023A].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, TIMESTAMP, SPEED, COURSE, HEADING from [ais_archive_2023B].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, TIMESTAMP, SPEED, COURSE, HEADING from [ais_archive_2024A].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, TIMESTAMP, SPEED, COURSE, HEADING from [ais_archive_2024B].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, TIMESTAMP, SPEED, COURSE, HEADING from [ais_archive_2025A].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, TIMESTAMP, SPEED, COURSE, HEADING from [ais_archive_2025B].[dbo].[POS_ARCHIVE] with (nolock)
) as ps
left JOIN [dbo].[V_SHIP_BATCH] as s with (nolock)
on ps.ship_id = s.ship_id
where ps.LON between {min_lon} and {max_lon}
  and ps.LAT between {min_lat} and {max_lat}
  and ps.speed between {speed_from} and {speed_to}
  and ps.TIMESTAMP between '{timestamp_start}' and '{timestamp_end}'
  {"and s.IMO > 0" if only_having_imo else ""}
"""

# Connect and count rows first
md = QgsProviderRegistry.instance().providerMetadata("mssql")
conn_metadata = md.findConnection(conn_name)
if not conn_metadata:
    raise Exception(f"Connection '{conn_name}' not found")

conn = md.createConnection(conn_metadata.uri(), {})
count_sql = f"select count(*) from ({sql}) as subquery"
count_result = conn.executeSql(count_sql)
total_count = count_result[0][0] if count_result else 0

# Ask user to confirm
reply = QMessageBox.question(None, "Confirm Export", f"Query will return {total_count} rows. Continue?", QMessageBox.Yes | QMessageBox.No)
if reply != QMessageBox.Yes:
    raise Exception("Cancelled by user")

# Run the actual query
results = conn.executeSql(sql)

# Explicit column names
header = [
    "SHIP_ID", "LON", "LAT", "TIMESTAMP", "SPEED", "COURSE", "HEADING",
    "shipname", "IMO", "comfleet_groupedtype", "type_summary",
    "type_name", "GRT", "DWT", "mt_link"
]

output_path = os.path.join(folder, output_file)
with open(output_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    if header:
        writer.writerow(header)
    for row in results:
        writer.writerow(row)

print(f"✅ Query executed and saved to {output_path}")
