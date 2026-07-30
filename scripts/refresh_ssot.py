import html
import json

from qgis.core import (
    QgsApplication,
    QgsProviderRegistry,
    QgsSettings,
    QgsTask
)
from qgis.PyQt.QtCore import Qt, QElapsedTimer, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout
)


class SsotRefreshDialog(QDialog):
    """
    Dialog for:

    1. Selecting a stored QGIS PostgreSQL connection.
    2. Showing the latest reporting.ssot_refresh_log row.
    3. Running geospatial.daily_jobs_ssot().
    4. Showing the latest log row after the refresh completes.
    """

    SETTINGS_KEY = "ssot_jobs/last_connection_name"
    DEFAULT_CONNECTION_NAME = "maritime_assets_geo_prod"

    ESTIMATED_SECONDS = 97  # 01:37

    REFRESH_SQL = """
        SELECT geospatial.daily_jobs_ssot();
    """

    LATEST_LOG_SQL = """
        SELECT row_to_json(srl)::text
        FROM reporting.ssot_refresh_log AS srl
        ORDER BY log_id DESC
        LIMIT 1;
    """

    TEST_CONNECTION_SQL = """
        SELECT 1;
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.settings = QgsSettings()

        self.task = None
        self.progress_dialog = None
        self.progress_timer = None
        self.elapsed_timer = None

        self.build_main_dialog()
        self.connect_signals()

    # ------------------------------------------------------------------
    # Main dialog
    # ------------------------------------------------------------------

    def build_main_dialog(self):
        """Build the initial connection and action dialog."""

        self.setWindowTitle("SSoT Refresh")
        self.setMinimumWidth(520)

        self.connection_edit = QLineEdit()
        self.connection_edit.setText(
            self.load_last_connection_name()
        )

        self.show_latest_button = QPushButton("Show Latest")
        self.refresh_button = QPushButton("Refresh")
        self.close_button = QPushButton("Close")

        self.show_latest_button.setDefault(True)

        form_layout = QFormLayout()
        form_layout.addRow(
            "Connection name:",
            self.connection_edit
        )

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.show_latest_button)
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.close_button)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(form_layout)
        main_layout.addSpacing(8)
        main_layout.addLayout(button_layout)

    def connect_signals(self):
        """Connect buttons and keyboard actions."""

        self.show_latest_button.clicked.connect(
            self.show_latest_log
        )

        self.refresh_button.clicked.connect(
            self.start_refresh
        )

        self.close_button.clicked.connect(
            self.close
        )

        self.connection_edit.returnPressed.connect(
            self.show_latest_log
        )

    # ------------------------------------------------------------------
    # Stored connection name
    # ------------------------------------------------------------------

    def load_last_connection_name(self):
        """Load the last successfully used connection name."""

        return self.settings.value(
            self.SETTINGS_KEY,
            self.DEFAULT_CONNECTION_NAME,
            type=str
        )

    def remember_connection_name(self, connection_name):
        """
        Remember the connection only after it has been used
        successfully.
        """

        self.settings.setValue(
            self.SETTINGS_KEY,
            connection_name
        )

    # ------------------------------------------------------------------
    # PostgreSQL connection handling
    # ------------------------------------------------------------------

    @staticmethod
    def postgres_metadata():
        """Return the QGIS PostgreSQL provider metadata object."""

        return (
            QgsProviderRegistry.instance()
            .providerMetadata("postgres")
        )

    def available_connection_names(self):
        """Return the stored PostgreSQL connection names from QGIS."""

        connections = self.postgres_metadata().connections()

        if isinstance(connections, dict):
            return list(connections.keys())

        return list(connections)

    def get_valid_connection_name(self):
        """
        Read and validate the entered connection name.

        The name is checked before createConnection() is called. This
        prevents an invalid name from being interpreted as a PostgreSQL
        connection URI pointing to localhost.
        """

        connection_name = self.connection_edit.text().strip()

        if not connection_name:
            self.show_warning(
                title="Missing Connection",
                message="Enter a PostgreSQL connection name."
            )
            self.focus_connection_field()
            return None

        try:
            available_names = self.available_connection_names()

        except Exception as error:
            self.show_error(
                title="Stored Connections Error",
                message=(
                    "QGIS could not read the stored PostgreSQL "
                    f"connections.\n\n{error}"
                )
            )
            self.focus_connection_field()
            return None

        if connection_name not in available_names:
            self.show_connection_not_found(
                connection_name,
                available_names
            )
            self.focus_connection_field()
            return None

        return connection_name

    def create_connection(self, connection_name):
        """Create a provider connection using a validated stored name."""

        return self.postgres_metadata().createConnection(
            connection_name
        )

    def test_connection(self, connection_name):
        """
        Test that the stored connection can execute SQL.

        Returns:
            tuple[bool, str | None]
        """

        try:
            connection = self.create_connection(connection_name)
            connection.executeSql(self.TEST_CONNECTION_SQL)
            return True, None

        except Exception as error:
            return False, str(error)

    def focus_connection_field(self):
        """Focus and select the connection-name field."""

        self.connection_edit.setFocus()
        self.connection_edit.selectAll()

    # ------------------------------------------------------------------
    # Latest-log retrieval
    # ------------------------------------------------------------------

    def fetch_latest_log(self, connection_name):
        """
        Fetch the latest refresh-log row.

        Returns:
            tuple[dict | None, str | None]
        """

        try:
            connection = self.create_connection(connection_name)
            rows = connection.executeSql(self.LATEST_LOG_SQL)

            if not rows:
                return None, None

            raw_json = rows[0][0]
            log_data = json.loads(raw_json)

            return log_data, None

        except Exception as error:
            return None, str(error)

    def show_latest_log(self):
        """Validate the connection, fetch the latest row, and show it."""

        connection_name = self.get_valid_connection_name()

        if not connection_name:
            return False

        log_data, error = self.fetch_latest_log(
            connection_name
        )

        if error:
            self.show_warning(
                title="Latest Log Could Not Be Read",
                message=(
                    "The latest refresh-log row could not be fetched."
                    f"\n\n{error}\n\n"
                    "Check the connection and try another stored "
                    "connection name."
                )
            )
            self.focus_connection_field()
            return False

        self.remember_connection_name(connection_name)

        if log_data is None:
            self.show_information(
                title="Latest SSoT Refresh",
                message=(
                    "The connection succeeded, but "
                    "reporting.ssot_refresh_log contains no rows."
                )
            )
            return True

        self.show_latest_log_message(log_data)
        return True

    # ------------------------------------------------------------------
    # Latest-log presentation
    # ------------------------------------------------------------------

    def show_latest_log_message(self, log_data):
        """
        Display the latest log row.

        The status area is green when critical_error_count is zero,
        red when it is greater than zero, and neutral otherwise.
        """

        error_count = self.parse_integer(
            log_data.get("critical_error_count")
        )

        status = self.determine_log_status(
            log_data,
            error_count
        )

        message_box = QMessageBox(self)
        message_box.setWindowTitle("Latest SSoT Refresh")
        message_box.setTextFormat(Qt.RichText)

        if status["level"] == "success":
            message_box.setIcon(QMessageBox.Information)

        elif status["level"] == "error":
            message_box.setIcon(QMessageBox.Critical)

        else:
            message_box.setIcon(QMessageBox.Warning)

        message_box.setText(
            self.build_log_html(
                log_data=log_data,
                status=status
            )
        )

        message_box.setStandardButtons(QMessageBox.Ok)
        message_box.setMinimumWidth(650)
        message_box.exec_()

    def determine_log_status(self, log_data, error_count):
        """
        Determine the latest-run status.

        NULL and zero critical errors are considered successful.
        Any value greater than zero is considered an error.
        """

        if error_count <= 0:
            return {
                "level": "success",
                "color": "#188038",
                "background": "#e6f4ea",
                "border": "#81c995",
                "label": "Latest Run: No critical errors"
            }

        return {
            "level": "error",
            "color": "#b3261e",
            "background": "#fce8e6",
            "border": "#e6a29d",
            "label": "Latest Run: Critical errors"
        }

    def build_log_html(self, log_data, status):
        """
        Build the HTML shown in the latest-log message box.

        Replace this function later to change only the visual layout.
        """

        rows_html = []

        for column, value in log_data.items():
            safe_column = html.escape(str(column))
            safe_value = html.escape(
                self.format_log_value(value)
            )

            rows_html.append(
                "<tr>"
                f"<td style='padding: 3px 14px 3px 0;'>"
                f"<b>{safe_column}</b>"
                "</td>"
                f"<td style='padding: 3px 0;'>{safe_value}</td>"
                "</tr>"
            )

        status_label = html.escape(status["label"])

        return f"""
            <div style="
                padding: 9px 12px;
                margin-bottom: 12px;
                color: {status["color"]};
                background-color: {status["background"]};
                border: 1px solid {status["border"]};
                border-radius: 5px;
                font-weight: bold;
            ">
                {status_label}
            </div>

            <table cellspacing="0" cellpadding="0">
                {''.join(rows_html)}
            </table>
        """

    @staticmethod
    def format_log_value(value):
        """Format a database value for display."""

        if value is None:
            return "NULL"

        if isinstance(value, bool):
            return "True" if value else "False"

        if isinstance(value, (dict, list)):
            return json.dumps(
                value,
                ensure_ascii=False
            )

        return str(value)

    @staticmethod
    def parse_integer(value):
        """
        Safely parse an integer-like database value.

        NULL is treated as zero.
        """

        if value is None:
            return 0

        try:
            return int(value)

        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # Refresh execution
    # ------------------------------------------------------------------

    def start_refresh(self):
        """Validate the connection and start the background refresh."""

        if self.task is not None:
            self.show_warning(
                title="Refresh Already Running",
                message="An SSoT refresh is already running."
            )
            return

        connection_name = self.get_valid_connection_name()

        if not connection_name:
            return

        connection_ok, error = self.test_connection(
            connection_name
        )

        if not connection_ok:
            self.show_warning(
                title="Connection Failed",
                message=(
                    f'The stored connection "{connection_name}" '
                    "could not be used.\n\n"
                    f"{error}\n\n"
                    "Enter another stored PostgreSQL connection name."
                )
            )
            self.focus_connection_field()
            return

        self.remember_connection_name(connection_name)
        self.set_main_controls_enabled(False)
        self.open_progress_dialog(connection_name)
        self.start_progress_timer()
        self.start_database_task(connection_name)

    def start_database_task(self, connection_name):
        """Create and register the QGIS background task."""

        self.task = QgsTask.fromFunction(
            "Run geospatial.daily_jobs_ssot()",
            self.execute_refresh_task,
            on_finished=self.refresh_finished,
            connection_name=connection_name
        )

        QgsApplication.taskManager().addTask(
            self.task
        )

    @staticmethod
    def execute_refresh_task(task, connection_name):
        """
        Worker-thread function that executes the PostgreSQL function.

        This function should not modify any Qt widgets.
        """

        if task.isCanceled():
            return {
                "success": False,
                "connection_name": connection_name,
                "reason": "Task was cancelled."
            }

        metadata = (
            QgsProviderRegistry.instance()
            .providerMetadata("postgres")
        )

        connection = metadata.createConnection(
            connection_name
        )

        connection.executeSql(
            SsotRefreshDialog.REFRESH_SQL
        )

        return {
            "success": True,
            "connection_name": connection_name
        }

    def refresh_finished(self, exception, result=None):
        """
        Handle completion of the background refresh.

        After a successful refresh, fetch and show the latest log row.
        """

        elapsed_seconds = self.get_elapsed_seconds()
        elapsed_text = self.format_duration(
            elapsed_seconds
        )

        self.stop_progress_timer()
        self.close_progress_dialog()

        self.task = None
        self.set_main_controls_enabled(True)

        if exception is not None:
            self.show_error(
                title="SSoT Refresh Failed",
                message=(
                    f"{exception}\n\n"
                    "Execution time before failure: "
                    f"{elapsed_text}"
                )
            )
            return

        if not result or not result.get("success"):
            reason = (
                result.get("reason")
                if isinstance(result, dict)
                else "The task did not return a successful result."
            )

            self.show_warning(
                title="SSoT Refresh Did Not Complete",
                message=(
                    f"{reason}\n\n"
                    f"Execution time: {elapsed_text}"
                )
            )
            return

        connection_name = result["connection_name"]

        # Fetch the new log row directly. The user is not shown a
        # separate success dialog before the log result.
        self.show_post_refresh_log(
            connection_name=connection_name,
            elapsed_text=elapsed_text
        )

    def show_post_refresh_log(
        self,
        connection_name,
        elapsed_text
    ):
        """
        Fetch and display the latest log after refresh completion.

        This is separate from show_latest_log() so post-refresh behavior
        can be changed independently later.
        """

        log_data, error = self.fetch_latest_log(
            connection_name
        )

        if error:
            self.show_warning(
                title="Refresh Completed, Log Read Failed",
                message=(
                    "geospatial.daily_jobs_ssot() finished, but the "
                    "latest log row could not be read.\n\n"
                    f"Execution time: {elapsed_text}\n\n"
                    f"{error}"
                )
            )
            return

        if log_data is None:
            self.show_warning(
                title="Refresh Completed",
                message=(
                    "geospatial.daily_jobs_ssot() finished, but no "
                    "row was found in reporting.ssot_refresh_log."
                    "\n\n"
                    f"Execution time: {elapsed_text}"
                )
            )
            return

        # Include the locally measured QGIS execution duration without
        # changing the database result.
        displayed_log = dict(log_data)
        displayed_log["qgis_execution_time"] = elapsed_text

        self.show_latest_log_message(
            displayed_log
        )

    # ------------------------------------------------------------------
    # Progress dialog
    # ------------------------------------------------------------------

    def open_progress_dialog(self, connection_name):
        """Create and show the running progress dialog."""

        self.progress_dialog = QDialog(self)
        self.progress_dialog.setWindowTitle(
            "Running SSoT Refresh"
        )
        self.progress_dialog.setMinimumWidth(500)
        self.progress_dialog.setModal(True)

        # PostgreSQL execution cannot be safely stopped merely by
        # closing this window, so accidental closure is disabled.
        self.progress_dialog.setWindowFlag(
            Qt.WindowCloseButtonHint,
            False
        )

        title_label = QLabel(
            "<b>Running geospatial.daily_jobs_ssot()</b>"
        )

        connection_label = QLabel(
            f"Connection: {html.escape(connection_name)}"
        )

        self.progress_bar = self.create_progress_bar()

        self.eta_label = QLabel(
            "Estimated time remaining: 01:37"
        )

        self.elapsed_label = QLabel(
            "Elapsed time: 00:00"
        )

        note_label = QLabel(
            "The database operation is running in the background. "
            "This window will close when it finishes."
        )
        note_label.setWordWrap(True)

        layout = QVBoxLayout(self.progress_dialog)
        layout.addWidget(title_label)
        layout.addWidget(connection_label)
        layout.addSpacing(8)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.eta_label)
        layout.addWidget(self.elapsed_label)
        layout.addSpacing(5)
        layout.addWidget(note_label)

        self.progress_dialog.show()

    @staticmethod
    def create_progress_bar():
        """
        Create a time-based progress bar.

        It reaches 100% at ESTIMATED_SECONDS and remains at 100%
        if the execution exceeds the estimated duration.
        """

        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        progress_bar.setFormat("%p%")
        progress_bar.setTextVisible(True)
        progress_bar.setMinimumHeight(22)

        progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #8aaec4;
                border-radius: 5px;
                background-color: #edf7fc;
                text-align: center;
            }

            QProgressBar::chunk {
                background-color: #79c8f2;
                border-radius: 4px;
            }
        """)

        return progress_bar

    def start_progress_timer(self):
        """Start elapsed-time and ETA tracking."""

        self.elapsed_timer = QElapsedTimer()
        self.elapsed_timer.start()

        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(200)
        self.progress_timer.timeout.connect(
            self.update_progress_display
        )
        self.progress_timer.start()

    def stop_progress_timer(self):
        """Stop and release the progress timer."""

        if self.progress_timer is not None:
            self.progress_timer.stop()
            self.progress_timer.deleteLater()
            self.progress_timer = None

    def update_progress_display(self):
        """
        Update elapsed time, ETA and time-based progress.

        Progress reaches 100% when ESTIMATED_SECONDS is reached.
        If execution continues, it remains at 100% while the ETA
        continues into negative time.
        """

        if self.elapsed_timer is None:
            return

        elapsed_seconds = self.get_elapsed_seconds()

        remaining_seconds = (
            self.ESTIMATED_SECONDS - elapsed_seconds
        )

        progress_percent = min(
            100,
            round(
                elapsed_seconds
                / self.ESTIMATED_SECONDS
                * 100
            )
        )

        self.progress_bar.setValue(progress_percent)

        self.elapsed_label.setText(
            "Elapsed time: "
            + self.format_duration(elapsed_seconds)
        )

        self.eta_label.setText(
            "Estimated time remaining: "
            + self.format_remaining_time(
                remaining_seconds
            )
        )

    def close_progress_dialog(self):
        """Close and release the progress dialog."""

        if self.progress_dialog is not None:
            self.progress_dialog.accept()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None

    def get_elapsed_seconds(self):
        """Return the current task duration in whole seconds."""

        if self.elapsed_timer is None:
            return 0

        return self.elapsed_timer.elapsed() // 1000

    @staticmethod
    def format_remaining_time(remaining_seconds):
        """
        Format ETA as MM:SS.

        When the estimate is exceeded, values continue as:
        -00:01, -00:02, etc.
        """

        if remaining_seconds >= 0:
            return SsotRefreshDialog.format_duration(
                remaining_seconds
            )

        return (
            "-"
            + SsotRefreshDialog.format_duration(
                abs(remaining_seconds)
            )
        )

    @staticmethod
    def format_duration(total_seconds):
        """Format seconds as MM:SS."""

        total_seconds = max(0, int(total_seconds))
        minutes, seconds = divmod(total_seconds, 60)

        return f"{minutes:02d}:{seconds:02d}"

    # ------------------------------------------------------------------
    # Main-dialog state
    # ------------------------------------------------------------------

    def set_main_controls_enabled(self, enabled):
        """Enable or disable the main dialog controls."""

        self.connection_edit.setEnabled(enabled)
        self.show_latest_button.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled)
        self.close_button.setEnabled(enabled)

        self.setWindowFlag(
            Qt.WindowCloseButtonHint,
            enabled
        )

        self.show()

    def closeEvent(self, event):
        """Prevent closure while the PostgreSQL job is running."""

        if self.task is not None:
            self.show_information(
                title="Refresh Running",
                message=(
                    "The dialog cannot be closed while the database "
                    "refresh is running."
                )
            )
            event.ignore()
            return

        event.accept()

    # ------------------------------------------------------------------
    # General message helpers
    # ------------------------------------------------------------------

    def show_connection_not_found(
        self,
        connection_name,
        available_names
    ):
        """Show an invalid-connection message with available names."""

        if available_names:
            available_text = "\n".join(
                f"• {name}"
                for name in sorted(available_names)
            )
        else:
            available_text = (
                "No stored PostgreSQL connections were found."
            )

        self.show_warning(
            title="Connection Not Found",
            message=(
                f'The PostgreSQL connection "{connection_name}" '
                "does not exist in QGIS.\n\n"
                "Available connections:\n"
                f"{available_text}\n\n"
                "Enter another stored connection name."
            )
        )

    def show_information(self, title, message):
        """Show a general informational message."""

        QMessageBox.information(
            self,
            title,
            message
        )

    def show_warning(self, title, message):
        """Show a warning message."""

        QMessageBox.warning(
            self,
            title,
            message
        )

    def show_error(self, title, message):
        """Show an error message."""

        QMessageBox.critical(
            self,
            title,
            message
        )


# ----------------------------------------------------------------------
# Launch
# ----------------------------------------------------------------------

# Close an older dialog instance left by a previous console execution.
try:
    if _ssot_refresh_dialog is not None:
        _ssot_refresh_dialog.close()
except (NameError, RuntimeError):
    pass


# A global reference prevents Python from garbage-collecting the dialog.
_ssot_refresh_dialog = SsotRefreshDialog(
    iface.mainWindow()
)

_ssot_refresh_dialog.show()
_ssot_refresh_dialog.raise_()
_ssot_refresh_dialog.activateWindow()