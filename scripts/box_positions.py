from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import (
    QApplication, QDialog, QLineEdit, QCheckBox, QPushButton, QHBoxLayout,
    QFormLayout, QLabel, QVBoxLayout, QFileDialog, QMessageBox
)
from qgis.core import QgsProviderRegistry, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.utils import iface
import csv
import os
import sys
import math

# ---------- Helpers ----------

def _norm_lon(lon):
    """Normalize longitude to [-180, 180]."""
    if math.isfinite(lon):
        lon = ((lon + 180.0) % 360.0) - 180.0
    return lon

def _clamp_lat(lat):
    """Clamp latitude to [-90, 90]."""
    if math.isfinite(lat):
        lat = max(-90.0, min(90.0, lat))
    return lat

def _format_num(x):
    """Format numeric for SQL with reasonable precision."""
    return f"{float(x):.6f}"

# ---------- Canvas extent -> geographic window ----------

canvas = iface.mapCanvas()
extent = canvas.extent()
crs_canvas = canvas.mapSettings().destinationCrs()

WORLD_HALF_3857 = 20037508.342789244  # meters (valid Web Mercator half world)
WORLD_W_3857 = 2 * WORLD_HALF_3857
WEBMERC_LAT_LIMIT = 85.0511287798066  # deg

# Transform extent corners to EPSG:4326, with clamping for EPSG:3857
if crs_canvas.authid() == 'EPSG:3857':
    # Clamp to valid 3857 world to avoid endless wrapped copies
    xmin_3857 = max(extent.xMinimum(),  -WORLD_HALF_3857)
    xmax_3857 = min(extent.xMaximum(),   WORLD_HALF_3857)
    ymin_3857 = max(extent.yMinimum(),  -WORLD_HALF_3857)
    ymax_3857 = min(extent.yMaximum(),   WORLD_HALF_3857)

    # Consider it "global" if width ≈ whole world
    lon_global = (xmax_3857 - xmin_3857) >= 0.99 * WORLD_W_3857

    crs_dest = QgsCoordinateReferenceSystem('EPSG:4326')
    xform = QgsCoordinateTransform(crs_canvas, crs_dest, QgsProject.instance())
    bl = xform.transform(xmin_3857, ymin_3857)
    tr = xform.transform(xmax_3857, ymax_3857)
    min_lon_raw, min_lat_raw = bl.x(), bl.y()
    max_lon_raw, max_lat_raw = tr.x(), tr.y()

elif crs_canvas.authid() == 'EPSG:4326':
    lon_global = False
    min_lon_raw, max_lon_raw = extent.xMinimum(), extent.xMaximum()
    min_lat_raw, max_lat_raw = extent.yMinimum(), extent.yMaximum()

else:
    # Other projected CRS: just transform without clamping
    lon_global = False
    crs_dest = QgsCoordinateReferenceSystem('EPSG:4326')
    xform = QgsCoordinateTransform(crs_canvas, crs_dest, QgsProject.instance())
    bl = xform.transform(extent.xMinimum(), extent.yMinimum())
    tr = xform.transform(extent.xMaximum(), extent.yMaximum())
    min_lon_raw, min_lat_raw = bl.x(), bl.y()
    max_lon_raw, max_lat_raw = tr.x(), tr.y()

# Latitude: clamp and order
min_lat = _clamp_lat(min_lat_raw)
max_lat = _clamp_lat(max_lat_raw)
if min_lat > max_lat:
    min_lat, max_lat = max_lat, min_lat

# If we're effectively global (or clearly at 3857's pole limits), expand latitude to full globe
lat_global = lon_global or (
    crs_canvas.authid() == 'EPSG:3857'
    and abs(min_lat + WEBMERC_LAT_LIMIT) < 0.05
    and abs(max_lat - WEBMERC_LAT_LIMIT) < 0.05
)
if lat_global:
    min_lat, max_lat = -90.0, 90.0

# Longitude: normalize; if global, force full range, else detect wrap
if lon_global:
    min_lon, max_lon = -180.0, 180.0
    lon_wrap = False
else:
    min_lon = _norm_lon(min_lon_raw)
    max_lon = _norm_lon(max_lon_raw)
    lon_wrap = min_lon > max_lon  # indicates interval crosses antimeridian

# Build WHERE snippets
if lon_global:
    lon_clause = "1=1"
elif lon_wrap:
    lon_clause = (
        f"(ps.LON BETWEEN {_format_num(min_lon)} AND 180) "
        f"OR (ps.LON BETWEEN -180 AND {_format_num(max_lon)})"
    )
else:
    lon_clause = f"ps.LON BETWEEN {_format_num(min_lon)} AND {_format_num(max_lon)}"

if lat_global:
    lat_clause = "1=1"
else:
    lat_clause = f"ps.LAT BETWEEN {_format_num(min_lat)} AND {_format_num(max_lat)}"

# ---------- UI Dialog ----------

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
        self.only_imo_checkbox.setChecked(str(self.settings.value("only_having_imo", "true")).lower() == "true")
        # Optional: ship_ids (comma-separated)
        self.ship_ids_input = QLineEdit(self.settings.value("ship_ids", ""))

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
        layout.addRow("Ship IDs (comma-separated):", self.ship_ids_input)

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
            "only_having_imo": self.only_imo_checkbox.isChecked(),
            "ship_ids": self.ship_ids_input.text(),
        }

# ---------- Run dialog ----------

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
ship_ids_text = values["ship_ids"]

# Ensure folder exists
if folder and not os.path.isdir(folder):
    os.makedirs(folder, exist_ok=True)

# Optional ship_id filter
ship_ids_clause = ""
if ship_ids_text.strip():
    ids = []
    for part in ship_ids_text.split(","):
        p = part.strip()
        if p:
            try:
                ids.append(int(p))
            except ValueError:
                pass  # skip non-numeric entries silently
    if ids:
        ship_ids_clause = f"  and ps.SHIP_ID in ({','.join(str(i) for i in ids)})"

# ---------- SQL ----------

sql = f"""
select
    ps.SHIP_ID,
    ps.LON,
    ps.LAT,
    ps.[TIMESTAMP],
    CAST(ps.SPEED AS INT) AS SPEED,
    ps.COURSE,
    ps.HEADING,
    s.shipname,
    s.IMO,
    s.comfleet_groupedtype,
    s.type_summary,
    s.type_name,
    s.GRT,
    s.DWT,
    'https://www.marinetraffic.com/en/ais/details/ships/shipid:' + CAST(ps.SHIP_ID AS VARCHAR) as mt_link
from (
    select SHIP_ID, LON, LAT, [TIMESTAMP], SPEED, COURSE, HEADING
        from [ais_archive_2022A].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, [TIMESTAMP], SPEED, COURSE, HEADING
        from [ais_archive_2022B].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, [TIMESTAMP], SPEED, COURSE, HEADING
        from [ais_archive_2023A].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, [TIMESTAMP], SPEED, COURSE, HEADING
        from [ais_archive_2023B].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, [TIMESTAMP], SPEED, COURSE, HEADING
        from [ais_archive_2024A].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, [TIMESTAMP], SPEED, COURSE, HEADING
        from [ais_archive_2024B].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, [TIMESTAMP], SPEED, COURSE, HEADING
        from [ais_archive_2025A].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, [TIMESTAMP], SPEED, COURSE, HEADING
        from [ais_archive_2025B].[dbo].[POS_ARCHIVE] with (nolock)
    union all
    select SHIP_ID, LON, LAT, [TIMESTAMP], SPEED, COURSE, HEADING
        from [ais_archive_2026A].[dbo].[POS_ARCHIVE] with (nolock)
) as ps
left join [dbo].[V_SHIP_BATCH] as s with (nolock)
    on ps.ship_id = s.ship_id
where {lon_clause}
  and {lat_clause}
  and CAST(ps.SPEED AS INT) between {speed_from} and {speed_to}
  and ps.[TIMESTAMP] between '{timestamp_start}' and '{timestamp_end}'
  {"and s.IMO > 0" if only_having_imo else ""}
{ship_ids_clause}
"""

# ---------- Execute ----------

md = QgsProviderRegistry.instance().providerMetadata("mssql")
conn_metadata = md.findConnection(conn_name)
if not conn_metadata:
    raise Exception(f"Connection '{conn_name}' not found")

conn = md.createConnection(conn_metadata.uri(), {})

# Run the actual query first
results = conn.executeSql(sql)

# Count results and ask user whether to save
total_count = len(results) if results else 0

if total_count == 0:
    QMessageBox.information(None, "No Results", "The query returned 0 rows. Nothing to save.")
    raise Exception("No rows returned")

reply = QMessageBox.question(
    None, "Confirm Save",
    f"Query returned {total_count} rows.\nDo you want to save them to CSV?",
    QMessageBox.Yes | QMessageBox.No
)
if reply != QMessageBox.Yes:
    raise Exception("Cancelled by user")

# Explicit column names
header = [
    "SHIP_ID", "LON", "LAT", "TIMESTAMP", "SPEED", "COURSE", "HEADING",
    "shipname", "IMO", "comfleet_groupedtype", "type_summary",
    "type_name", "GRT", "DWT", "mt_link"
]

# Write CSV
output_path = os.path.join(folder, output_file)
with open(output_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    if header:
        writer.writerow(header)
    for row in results:
        writer.writerow(row)

print(f"✅ Query executed and saved to {output_path}")




