from qgis.PyQt.QtCore import QSettings, QVariant
from qgis.PyQt.QtWidgets import (
    QApplication, QDialog, QLineEdit, QCheckBox, QPushButton, QHBoxLayout,
    QFormLayout, QLabel, QVBoxLayout, QFileDialog, QMessageBox
)
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProviderRegistry,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorLayer,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsMarkerSymbol,
    Qgis
)
from qgis.utils import iface
from qgis.PyQt.QtWidgets import QApplication as QtApp
import csv
import os
import sys
import math

# =========================================================
# ----------------------- Helpers -------------------------
# =========================================================

def _msg(level, text, title="MT Box", duration=6):
    """QGIS message bar helper."""
    try:
        iface.messageBar().pushMessage(title, text, level=level, duration=duration)
        QtApp.processEvents()  # ensure it renders in plugin runners too
    except Exception:
        print(f"[{title}] {text}")

def _clear_msgbar():
    """Clear message bar widgets."""
    try:
        iface.messageBar().clearWidgets()
        QtApp.processEvents()
    except Exception:
        pass

def _show_running(text="Running query…", title="MT Box"):
    """
    Show a persistent 'running...' message that reliably appears even when
    the next call is blocking (e.g., DB query).
    """
    _clear_msgbar()
    try:
        iface.messageBar().pushMessage(title, text, level=Qgis.Info, duration=0)  # persistent
        QtApp.processEvents()
        # call processEvents twice to force paint on some runners/themes
        QtApp.processEvents()
    except Exception:
        print(f"[{title}] {text}")

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

def _parse_rgb(rgb_text):
    """Parse 'rgb( 160, 204, 114 )' -> QColor."""
    if not rgb_text:
        return QColor(201, 201, 201)
    s = rgb_text.strip().lower()
    if s.startswith("rgb"):
        inside = s[s.find("(") + 1:s.find(")")]
        parts = [p.strip() for p in inside.split(",")]
        if len(parts) >= 3:
            try:
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                return QColor(r, g, b)
            except Exception:
                pass
    return QColor(201, 201, 201)

def _mk_marker_symbol(color: QColor, size_mm=2.4, outline_color=QColor(0, 0, 0), outline_mm=0.1):
    sym = QgsMarkerSymbol.createSimple({})
    sym.setColor(color)
    sym.setSize(size_mm)
    try:
        sym.symbolLayer(0).setStrokeColor(outline_color)
        sym.symbolLayer(0).setStrokeWidth(outline_mm)
    except Exception:
        pass
    return sym

# --- QVariant-safe conversions ---

def _to_str(v):
    if v is None:
        return ""
    try:
        if isinstance(v, QVariant):
            return v.toString()
    except Exception:
        pass
    return str(v)

def _to_float(v):
    if v is None:
        return None
    try:
        if isinstance(v, QVariant):
            d, ok = v.toDouble()
            return float(d) if ok else None
    except Exception:
        pass
    try:
        return float(v)
    except Exception:
        return None

def _to_int(v):
    if v is None:
        return None
    try:
        if isinstance(v, QVariant):
            i, ok = v.toInt()
            return int(i) if ok else None
    except Exception:
        pass
    try:
        return int(float(v))
    except Exception:
        return None

def _to_long(v):
    if v is None:
        return None
    try:
        if isinstance(v, QVariant):
            i, ok = v.toLongLong()
            return int(i) if ok else None
    except Exception:
        pass
    return _to_int(v)

# =========================================================
# ------------ Canvas extent -> geographic window ----------
# =========================================================

try:
    canvas = iface.mapCanvas()
    extent = canvas.extent()
    crs_canvas = canvas.mapSettings().destinationCrs()

    WORLD_HALF_3857 = 20037508.342789244  # meters
    WORLD_W_3857 = 2 * WORLD_HALF_3857
    WEBMERC_LAT_LIMIT = 85.0511287798066  # deg

    if crs_canvas.authid() == 'EPSG:3857':
        xmin_3857 = max(extent.xMinimum(), -WORLD_HALF_3857)
        xmax_3857 = min(extent.xMaximum(),  WORLD_HALF_3857)
        ymin_3857 = max(extent.yMinimum(), -WORLD_HALF_3857)
        ymax_3857 = min(extent.yMaximum(),  WORLD_HALF_3857)

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
        lon_global = False
        crs_dest = QgsCoordinateReferenceSystem('EPSG:4326')
        xform = QgsCoordinateTransform(crs_canvas, crs_dest, QgsProject.instance())
        bl = xform.transform(extent.xMinimum(), extent.yMinimum())
        tr = xform.transform(extent.xMaximum(), extent.yMaximum())
        min_lon_raw, min_lat_raw = bl.x(), bl.y()
        max_lon_raw, max_lat_raw = tr.x(), tr.y()

    min_lat = _clamp_lat(min_lat_raw)
    max_lat = _clamp_lat(max_lat_raw)
    if min_lat > max_lat:
        min_lat, max_lat = max_lat, min_lat

    lat_global = lon_global or (
        crs_canvas.authid() == 'EPSG:3857'
        and abs(min_lat + WEBMERC_LAT_LIMIT) < 0.05
        and abs(max_lat - WEBMERC_LAT_LIMIT) < 0.05
    )
    if lat_global:
        min_lat, max_lat = -90.0, 90.0

    if lon_global:
        min_lon, max_lon = -180.0, 180.0
        lon_wrap = False
    else:
        min_lon = _norm_lon(min_lon_raw)
        max_lon = _norm_lon(max_lon_raw)
        lon_wrap = min_lon > max_lon

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

except Exception as e:
    _msg(Qgis.Warning, f"Failed to read canvas extent; using global bbox. ({e})")
    lon_clause = "1=1"
    lat_clause = "1=1"

# =========================================================
# ----------------------- UI Dialog -----------------------
# =========================================================

class InputDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MSSQL Query Exporter")
        self.settings = QSettings()

        self.conn_name_input = QLineEdit(self.settings.value("conn_name", "dbdev"))
        self.folder_path_input = QLineEdit(self.settings.value("folder_path", ""))  # default empty
        self.output_file_input = QLineEdit(self.settings.value("output_file", ""))  # default empty
        self.speed_from_input = QLineEdit(self.settings.value("speed_from", "0"))
        self.speed_to_input = QLineEdit(self.settings.value("speed_to", "0"))
        self.timestamp_start_input = QLineEdit(self.settings.value("timestamp_start", "2026-02-01 00:00"))
        self.timestamp_end_input = QLineEdit(self.settings.value("timestamp_end", "2026-02-28 00:00"))
        self.only_imo_checkbox = QCheckBox("Only Having IMO")
        self.only_imo_checkbox.setChecked(str(self.settings.value("only_having_imo", "true")).lower() == "true")
        self.ship_ids_input = QLineEdit(self.settings.value("ship_ids", ""))

        self.select_button = QPushButton("Change Folder")
        self.select_button.clicked.connect(self.select_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.folder_path_input)
        folder_layout.addWidget(self.select_button)

        layout = QFormLayout()
        layout.addRow("Connection Name:", self.conn_name_input)
        layout.addRow(QLabel("Output Folder (leave empty = no CSV):"))
        layout.addRow(folder_layout)
        layout.addRow("Output File Name (optional):", self.output_file_input)
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

# =========================================================
# -------------------------- Run --------------------------
# =========================================================

try:
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = InputDialog()

    if not dialog.exec_():
        _msg(Qgis.Warning, "Cancelled.")
        raise Exception("Cancelled")

    values = dialog.get_values()
    settings = QSettings()
    for key, val in values.items():
        settings.setValue(key, str(val))

    conn_name = values["conn_name"].strip()
    folder = values["folder_path"].strip()
    output_file = values["output_file"].strip()  # may be empty
    speed_from = values["speed_from"]
    speed_to = values["speed_to"]
    timestamp_start = values["timestamp_start"]
    timestamp_end = values["timestamp_end"]
    only_having_imo = values["only_having_imo"]
    ship_ids_text = values["ship_ids"]

    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)

    ship_ids_clause = ""
    if ship_ids_text.strip():
        ids = []
        for part in ship_ids_text.split(","):
            p = part.strip()
            if p:
                try:
                    ids.append(int(p))
                except ValueError:
                    pass
        if ids:
            ship_ids_clause = f"  and ps.SHIP_ID in ({','.join(str(i) for i in ids)})"

    # mt_link removed
    sql = f"""
select
    ps.SHIP_ID,
    ps.LON,
    ps.LAT,
    ps.[TIMESTAMP],
    CAST(ps.SPEED AS INT) AS SPEED,
    CAST(ps.COURSE AS INT) AS COURSE,
    CAST(ps.HEADING AS INT) AS HEADING,
    s.shipname,
    s.IMO,
    s.comfleet_groupedtype,
    s.type_summary,
    s.type_name,
    s.GRT,
    s.DWT
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

    md = QgsProviderRegistry.instance().providerMetadata("mssql")
    conn_metadata = md.findConnection(conn_name)
    if not conn_metadata:
        _msg(Qgis.Warning, f"Connection '{conn_name}' not found.")
        raise Exception(f"Connection '{conn_name}' not found")

    conn = md.createConnection(conn_metadata.uri(), {})

    # -------------------------------------------------------
    # Reliable "Running query..." message (forces UI paint)
    # -------------------------------------------------------
    _show_running("Running query…")

    # Console prints (you asked to keep them)
    print("▶ Running query...")
    results = conn.executeSql(sql)
    print("✔ Query finished.")

    _clear_msgbar()

    total_count = len(results) if results else 0
    if total_count == 0:
        _msg(Qgis.Warning, "No results (0 rows).")
        raise Exception("No rows returned")

    # ---------------------- Save CSV (only if folder provided) ----------------------
    header = [
        "SHIP_ID", "LON", "LAT", "TIMESTAMP", "SPEED", "COURSE", "HEADING",
        "shipname", "IMO", "comfleet_groupedtype", "type_summary",
        "type_name", "GRT", "DWT"
    ]

    if folder:
        reply = QMessageBox.question(
            None, "Confirm Save",
            f"Query returned {total_count} rows.\nDo you want to save them to CSV?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            outname = output_file if output_file else "output.csv"
            output_path = os.path.join(folder, outname)
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                for row in results:
                    writer.writerow(row)
            print(f"✅ CSV saved to {output_path}")
        else:
            print("ℹ️ CSV save declined.")
    else:
        print("ℹ️ Output folder empty → CSV not saved (no prompt).")

    # ---------------------- Replace memory layer + symbology ----------------------
    LAYER_NAME = "MT Box positions"

    prev_category_state = {}  # value(str) -> bool
    project = QgsProject.instance()
    root = project.layerTreeRoot()

    existing = project.mapLayersByName(LAYER_NAME)
    if existing:
        old_layer = existing[0]
        if old_layer.renderer() and isinstance(old_layer.renderer(), QgsCategorizedSymbolRenderer):
            try:
                for cat in old_layer.renderer().categories():
                    prev_category_state[str(cat.value())] = bool(cat.renderState())
            except Exception:
                pass
        project.removeMapLayer(old_layer.id())

    crs_src = QgsCoordinateReferenceSystem("EPSG:4326")
    crs_dst = project.crs()
    xform_to_project = QgsCoordinateTransform(crs_src, crs_dst, project)

    mem = QgsVectorLayer(f"Point?crs={crs_dst.authid()}", LAYER_NAME, "memory")
    pr = mem.dataProvider()

    fields = QgsFields()
    fields.append(QgsField("SHIP_ID", QVariant.Int))
    fields.append(QgsField("LON", QVariant.Double))
    fields.append(QgsField("LAT", QVariant.Double))
    fields.append(QgsField("TIMESTAMP", QVariant.String))
    fields.append(QgsField("SPEED", QVariant.Int))
    fields.append(QgsField("COURSE", QVariant.Int))
    fields.append(QgsField("HEADING", QVariant.Int))
    fields.append(QgsField("shipname", QVariant.String))
    fields.append(QgsField("IMO", QVariant.LongLong))
    fields.append(QgsField("comfleet_groupedtype", QVariant.String))
    fields.append(QgsField("type_summary", QVariant.String))
    fields.append(QgsField("type_name", QVariant.String))
    fields.append(QgsField("GRT", QVariant.Double))
    fields.append(QgsField("DWT", QVariant.Double))
    pr.addAttributes(fields)
    mem.updateFields()

    feats = []
    for row in results:
        lon = _to_float(row[1])
        lat = _to_float(row[2])
        if lon is None or lat is None:
            continue

        try:
            pt_proj = xform_to_project.transform(QgsPointXY(lon, lat))
        except Exception:
            continue

        f = QgsFeature(mem.fields())
        f.setGeometry(QgsGeometry.fromPointXY(pt_proj))
        f.setAttributes([
            _to_int(row[0]),
            lon,
            lat,
            _to_str(row[3]),
            _to_int(row[4]),
            _to_int(row[5]),
            _to_int(row[6]),
            _to_str(row[7]),
            _to_long(row[8]),
            _to_str(row[9]),
            _to_str(row[10]),
            _to_str(row[11]),
            _to_float(row[12]),
            _to_float(row[13]),
        ])
        feats.append(f)

    pr.addFeatures(feats)
    mem.updateExtents()

    COLOR_MAP = {
        "CONTAINER SHIPS":    "rgb( 160, 204, 114 )",
        "DRY BULK":           "rgb( 183, 153, 77 )",
        "DRY BREAKBULK":      "rgb( 225, 201, 98 )",
        "WET BULK":           "rgb( 51, 158, 233 )",
        "LPG CARRIERS":       "rgb( 225, 105, 173 )",
        "LNG CARRIERS":       "rgb( 225, 90, 173 )",
        "PASSENGER SHIPS":    "rgb( 79, 255, 232 )",
        "RO/RO":              "rgb( 153, 153, 153 )",
        "OFFSHORE/RIGS":      "rgb( 215, 105, 54 )",
        "PLEASURE CRAFT":     "rgb( 246, 215, 246 )",
        "FISHING":            "rgb( 246, 215, 246 )",
        "SUPPORTING VESSELS": "rgb( 186, 208, 181 )",
        "OTHER MARKETS":      "rgb( 186, 208, 181 )",
    }
    DEFAULT_COLOR = QColor(201, 201, 201)

    idx = mem.fields().indexOf("comfleet_groupedtype")
    unique_vals = set()
    for ft in mem.getFeatures():
        v = ft.attribute(idx)
        unique_vals.add("" if v is None else str(v))

    categories = []

    for k, rgb in COLOR_MAP.items():
        sym = _mk_marker_symbol(_parse_rgb(rgb))
        cat = QgsRendererCategory(k, sym, k)
        if str(k) in prev_category_state:
            cat.setRenderState(prev_category_state[str(k)])
        categories.append(cat)

    other_vals = sorted([v for v in unique_vals if v and v not in COLOR_MAP])
    for v in other_vals:
        sym = _mk_marker_symbol(DEFAULT_COLOR)
        cat = QgsRendererCategory(v, sym, v)
        if str(v) in prev_category_state:
            cat.setRenderState(prev_category_state[str(v)])
        categories.append(cat)

    if "" in unique_vals:
        sym = _mk_marker_symbol(DEFAULT_COLOR)
        cat = QgsRendererCategory("", sym, "(empty)")
        if "" in prev_category_state:
            cat.setRenderState(prev_category_state[""])
        categories.append(cat)

    renderer = QgsCategorizedSymbolRenderer("comfleet_groupedtype", categories)
    mem.setRenderer(renderer)

    # Add layer straight at TOP of layer tree
    project.addMapLayer(mem, False)  # do not auto-add to legend
    root.insertLayer(0, mem)         # insert at top (above all groups/layers)

    iface.mapCanvas().refresh()
    _msg(Qgis.Success, f"Layer updated: {len(feats)} positions imported")

except Exception as e:
    _clear_msgbar()
    _msg(Qgis.Warning, str(e))
    raise
