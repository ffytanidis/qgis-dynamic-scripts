# Paste into the QGIS Python Console
from qgis.PyQt import QtWidgets, QtGui

def show_selected_geom_wkt():
    layer = iface.activeLayer()
    if not layer or layer.type() != layer.VectorLayer:
        QtWidgets.QMessageBox.warning(None, "No Layer", "Select a vector layer first.")
        return

    selected_features = layer.selectedFeatures()
    if not selected_features:
        QtWidgets.QMessageBox.warning(None, "No Selection", "No features selected.")
        return

    geom = selected_features[0].geometry()
    if geom is None or geom.isEmpty():
        QtWidgets.QMessageBox.warning(None, "Empty Geometry", "Selected feature has no geometry.")
        return

    wkt = geom.asWkt()

    # Dialog with word wrap and vertical scrollbar
    dlg = QtWidgets.QDialog(None)
    dlg.setWindowTitle("Selected Geometry WKT")
    dlg.resize(700, 450)

    layout = QtWidgets.QVBoxLayout(dlg)

    text = QtWidgets.QTextEdit(dlg)
    text.setReadOnly(True)
    text.setPlainText(wkt)

    # Monospace font for clarity
    font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
    text.setFont(font)

    # Enable wrapping and only vertical scrollbar
    text.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
    text.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    layout.addWidget(text)

    # Buttons: Copy and OK
    buttons = QtWidgets.QDialogButtonBox(dlg)
    copy_btn = buttons.addButton("Copy", QtWidgets.QDialogButtonBox.ActionRole)
    ok_btn = buttons.addButton(QtWidgets.QDialogButtonBox.Ok)
    layout.addWidget(buttons)

    def copy_and_close():
        QtWidgets.QApplication.clipboard().setText(text.toPlainText())
        dlg.accept()

    copy_btn.clicked.connect(copy_and_close)
    ok_btn.clicked.connect(dlg.accept)

    dlg.exec_()

show_selected_geom_wkt()
