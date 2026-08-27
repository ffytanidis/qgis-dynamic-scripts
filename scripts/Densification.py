import math
from pyproj import Transformer
from qgis.PyQt.QtWidgets import QInputDialog, QProgressBar, QMessageBox
from qgis.core import QgsWkbTypes, QgsGeometry, QgsPointXY, Qgis
from qgis.utils import iface

bar = iface.messageBar()

def _msg(title, text, level, duration):
    bar.pushMessage(title, text, level=level, duration=duration)

msg_ok   = lambda t, d=5: _msg("Success", t, Qgis.Success, d)
msg_warn = lambda t, d=6: _msg("Warning", t, Qgis.Warning, d)
msg_err  = lambda t, d=8: _msg("Error",   t, Qgis.Critical, d)


# ---------------------------------------------------------------------
# Coordinate transformations
# ---------------------------------------------------------------------

to_3857 = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:3857",
    always_xy=True
).transform

to_4326 = Transformer.from_crs(
    "EPSG:3857",
    "EPSG:4326",
    always_xy=True
).transform

hypot = math.hypot
ceil = math.ceil
Qpt = QgsPointXY


# ---------------------------------------------------------------------
# Generic point-sequence helpers
#
# Works for:
#   - polygon rings
#   - LineStrings
#
# The input is simply an ordered sequence of QgsPointXY.
# ---------------------------------------------------------------------

def sequence_needs_densify_3857_pts(points, max_m):
    """
    Early-exit scan of an ordered point sequence.

    Returns True if at least one vertex-to-vertex segment exceeds max_m
    when measured after transformation to EPSG:3857.
    """
    if not points or len(points) < 2:
        return False

    p0 = points[0]
    x1, y1 = to_3857(p0.x(), p0.y())

    for p in points[1:]:
        x2, y2 = to_3857(p.x(), p.y())

        if hypot(x2 - x1, y2 - y1) > max_m:
            return True

        x1, y1 = x2, y2

    return False


def densify_sequence_3857_pts(points, max_m):
    """
    Densify an ordered point sequence.

    For every existing segment:
      1. Transform endpoints to EPSG:3857
      2. Measure straight-line Mercator distance
      3. Split into enough equal pieces that each resulting segment
         is <= max_m
      4. Transform newly inserted vertices back to EPSG:4326

    Returns:
        (new_points, changed_bool)
    """
    npts = len(points)

    if npts < 2:
        return points, False

    out = []
    changed = False

    p_prev = points[0]

    lon1 = p_prev.x()
    lat1 = p_prev.y()

    X1, Y1 = to_3857(lon1, lat1)

    for p in points[1:]:

        lon2 = p.x()
        lat2 = p.y()

        X2, Y2 = to_3857(lon2, lat2)

        dX = X2 - X1
        dY = Y2 - Y1

        dist_m = hypot(dX, dY)

        nseg = max(
            1,
            int(ceil(dist_m / max_m))
        )

        if nseg > 1:
            changed = True

        # Preserve original segment start
        out.append(Qpt(lon1, lat1))

        # Insert intermediate points if needed
        if nseg > 1:

            inv = 1.0 / nseg

            for i in range(1, nseg):

                fraction = i * inv

                xi = X1 + dX * fraction
                yi = Y1 + dY * fraction

                loni, lati = to_4326(xi, yi)

                out.append(
                    Qpt(loni, lati)
                )

        # Advance to next original vertex
        lon1 = lon2
        lat1 = lat2
        X1 = X2
        Y1 = Y2

    # Preserve final original vertex
    out.append(
        Qpt(lon1, lat1)
    )

    return out, changed


# ---------------------------------------------------------------------
# Polygon / MultiPolygon
# ---------------------------------------------------------------------

def densify_polygon_3857(geom, max_m):
    """
    Densify Polygon or MultiPolygon geometry.

    Handles:
      - exterior rings
      - interior rings / holes

    Returns:
        (new_geometry, changed_bool)
    """

    polys = (
        geom.asMultiPolygon()
        if geom.isMultipart()
        else [geom.asPolygon()]
    )

    # -------------------------------------------------------------
    # Early exit
    # -------------------------------------------------------------

    needs = False

    for poly in polys:

        if not poly:
            continue

        # Exterior ring
        if sequence_needs_densify_3857_pts(
            poly[0],
            max_m
        ):
            needs = True
            break

        # Interior rings
        for hole in poly[1:]:

            if sequence_needs_densify_3857_pts(
                hole,
                max_m
            ):
                needs = True
                break

        if needs:
            break

    if not needs:
        return QgsGeometry(geom), False

    # -------------------------------------------------------------
    # Densify
    # -------------------------------------------------------------

    new_mp = []
    changed_any = False

    for poly in polys:

        if not poly:
            continue

        exterior, changed_ext = densify_sequence_3857_pts(
            poly[0],
            max_m
        )

        changed_any = changed_any or changed_ext

        holes = []

        for hole in poly[1:]:

            new_hole, changed_hole = densify_sequence_3857_pts(
                hole,
                max_m
            )

            changed_any = changed_any or changed_hole

            holes.append(new_hole)

        new_mp.append(
            [exterior] + holes
        )

    if geom.isMultipart():

        new_geom = QgsGeometry.fromMultiPolygonXY(
            new_mp
        )

    else:

        new_geom = QgsGeometry.fromPolygonXY(
            new_mp[0]
        )

    return new_geom, changed_any


# ---------------------------------------------------------------------
# LineString / MultiLineString
# ---------------------------------------------------------------------

def densify_line_3857(geom, max_m):
    """
    Densify LineString or MultiLineString geometry.

    Returns:
        (new_geometry, changed_bool)
    """

    lines = (
        geom.asMultiPolyline()
        if geom.isMultipart()
        else [geom.asPolyline()]
    )

    # -------------------------------------------------------------
    # Early exit
    # -------------------------------------------------------------

    needs = False

    for line in lines:

        if sequence_needs_densify_3857_pts(
            line,
            max_m
        ):
            needs = True
            break

    if not needs:
        return QgsGeometry(geom), False

    # -------------------------------------------------------------
    # Densify
    # -------------------------------------------------------------

    new_lines = []
    changed_any = False

    for line in lines:

        new_line, changed = densify_sequence_3857_pts(
            line,
            max_m
        )

        changed_any = changed_any or changed

        new_lines.append(new_line)

    if geom.isMultipart():

        new_geom = QgsGeometry.fromMultiPolylineXY(
            new_lines
        )

    else:

        new_geom = QgsGeometry.fromPolylineXY(
            new_lines[0]
        )

    return new_geom, changed_any


# ---------------------------------------------------------------------
# Generic geometry dispatcher
# ---------------------------------------------------------------------

def densify_geometry_3857(geom, max_m):
    """
    Densify supported geometry types.

    Supported:
      - Polygon
      - MultiPolygon
      - LineString
      - MultiLineString

    Unsupported geometries are returned unchanged.

    Returns:
        (new_geometry, changed_bool, supported_bool)
    """

    if geom.isEmpty():
        return QgsGeometry(geom), False, False

    geom_type = geom.type()

    if geom_type == QgsWkbTypes.PolygonGeometry:

        new_geom, changed = densify_polygon_3857(
            geom,
            max_m
        )

        return new_geom, changed, True

    if geom_type == QgsWkbTypes.LineGeometry:

        new_geom, changed = densify_line_3857(
            geom,
            max_m
        )

        return new_geom, changed, True

    return QgsGeometry(geom), False, False


# =====================================================================
# MAIN
# =====================================================================

progress_handle = None

try:

    layer = iface.activeLayer()

    if layer is None:
        msg_err("No active layer selected.")
        raise SystemExit

    # -----------------------------------------------------------------
    # CRS check
    # -----------------------------------------------------------------

    if layer.crs().authid() != "EPSG:4326":

        msg_err(
            f"Layer CRS is {layer.crs().authid()}, expected EPSG:4326."
        )

        raise SystemExit

    # -----------------------------------------------------------------
    # Edit-mode check
    # -----------------------------------------------------------------

    if not layer.isEditable():

        msg_warn(
            "Layer is not in edit mode. Enable editing and re-run."
        )

        raise SystemExit

    # -----------------------------------------------------------------
    # Selection
    # -----------------------------------------------------------------

    sel_count = layer.selectedFeatureCount()
    apply_all = False

    if sel_count == 0:

        ans = QMessageBox.question(
            iface.mainWindow(),
            "No selection",
            (
                "No features are selected.\n\n"
                "Apply densification to ALL features "
                "of the active layer?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if ans != QMessageBox.Yes:

            msg_warn("Operation cancelled.")
            raise SystemExit

        apply_all = True

    n = (
        int(layer.featureCount())
        if apply_all
        else int(sel_count)
    )

    if n == 0:

        msg_warn("No features to process.")
        raise SystemExit

    # -----------------------------------------------------------------
    # Maximum segment length
    # -----------------------------------------------------------------

    max_km, ok = QInputDialog.getDouble(
        iface.mainWindow(),
        "Mercator (EPSG:3857) densify geometries",
        (
            f"{n} feature(s) will be processed.\n\n"
            "Supported geometry types:\n"
            "• Polygon / MultiPolygon\n"
            "• LineString / MultiLineString\n\n"
            "Enter maximum segment length (km) in EPSG:3857:"
        ),
        value=100.0,
        min=0.001,
        decimals=3
    )

    if not ok:

        msg_warn(
            "Operation cancelled by user."
        )

        raise SystemExit

    max_m = max_km * 1000.0

    # -----------------------------------------------------------------
    # Progress bar
    # -----------------------------------------------------------------

    progress_msg = bar.createMessage(
        "Densifying features…"
    )

    progress = QProgressBar()

    progress.setRange(
        0,
        n
    )

    progress.setValue(0)

    progress_msg.layout().addWidget(
        progress
    )

    progress_handle = bar.pushWidget(
        progress_msg,
        Qgis.Info
    )

    # -----------------------------------------------------------------
    # Counters
    # -----------------------------------------------------------------

    changed = 0
    unchanged = 0
    skipped = 0

    # Local bindings for speed
    set_prog = progress.setValue
    change_geom = layer.changeGeometry

    # -----------------------------------------------------------------
    # Begin grouped edit command
    # -----------------------------------------------------------------

    layer.beginEditCommand(
        "Mercator densify geometries"
    )

    try:

        it = (
            layer.getFeatures()
            if apply_all
            else layer.getSelectedFeatures()
        )

        for i, f in enumerate(
            it,
            start=1
        ):

            g = f.geometry()

            # ---------------------------------------------------------
            # Empty geometry
            # ---------------------------------------------------------

            if g.isEmpty():

                skipped += 1
                set_prog(i)
                continue

            # ---------------------------------------------------------
            # Densify
            # ---------------------------------------------------------

            ng, did_change, supported = densify_geometry_3857(
                g,
                max_m
            )

            if not supported:

                skipped += 1
                set_prog(i)
                continue

            if did_change:

                ok_change = change_geom(
                    f.id(),
                    ng
                )

                if ok_change:
                    changed += 1
                else:
                    skipped += 1

            else:

                unchanged += 1

            set_prog(i)

    finally:

        layer.endEditCommand()
        layer.triggerRepaint()

    # -----------------------------------------------------------------
    # Result
    # -----------------------------------------------------------------

    if changed == 0:

        if skipped == 0:

            msg_warn(
                (
                    f"Finished. No geometry changes were necessary. "
                    f"Checked {n} feature(s)."
                )
            )

        else:

            msg_warn(
                (
                    f"Finished. No geometries changed. "
                    f"Unchanged: {unchanged}. "
                    f"Skipped: {skipped}."
                )
            )

    else:

        result = (
            f"Finished. Modified {changed} of {n} feature(s)."
        )

        if unchanged:
            result += f" Unchanged: {unchanged}."

        if skipped:
            result += f" Skipped: {skipped}."

        result += " Edits are NOT saved."

        msg_ok(result)


except SystemExit:
    pass

except Exception as e:

    msg_err(
        f"Unexpected error: {e}"
    )

finally:

    if progress_handle is not None:

        try:
            bar.popWidget(
                progress_handle
            )
        except Exception:
            pass
