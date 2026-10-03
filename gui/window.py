import json
from datetime import datetime as _dt
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QGroupBox, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit,
    QMessageBox, QHeaderView, QDialog, QScrollArea,
)
from PySide6.QtCore import Qt
from dotenv import set_key, dotenv_values

from collectors.storage import load_snapshots
from ml.scoring import predict_sample_total, predict_devices
from config.settings import (
    PROJECT_ROOT,
    DATASET_FILE,
    ISP_FILE,
)
from gui.workers import (
    RouterCollectorWorker,
    IspCollectorWorker,
    IspLoginWorker,
    AnalysisWorker,
)


ENV_PATH = PROJECT_ROOT / ".env"
MODEL_FILE = PROJECT_ROOT / "data" / "model.json"


# ==============================================================
# ISP Login Dialog
# ==============================================================

class IspLoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Login to AsiaTech Panel")
        self.resize(520, 260)

        layout = QVBoxLayout(self)

        info = QLabel(
            "1. A browser window will open.\n"
            "2. In the browser, log into the AsiaTech panel "
            "(username, password, CAPTCHA).\n"
            "3. After successfully logging in, click the "
            "'💾 Save Session' button here.\n"
            "4. The browser closes and the session is saved."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.status = QLabel("Preparing...")
        self.status.setStyleSheet("color: #333; font-style: italic;")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save Session")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)

        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self._worker = IspLoginWorker()
        self._worker.log.connect(self._on_log)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_log(self, msg: str):
        self.status.setText(msg)
        if "Please log in to the panel" in msg:
            self.save_btn.setEnabled(True)

    def _on_save(self):
        self.save_btn.setEnabled(False)
        self.status.setText("Saving session...")
        self._worker.save_session()

    def _on_cancel(self):
        self._worker.cancel()
        self.reject()

    def _on_done(self, ok: bool):
        if ok:
            QMessageBox.information(self, "Success", "Session saved successfully.")
            self.accept()
        else:
            QMessageBox.warning(
                self, "Failed", "Failed to save session. Please try again."
            )
            self.reject()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        event.accept()


# ==============================================================
# Settings Tab
# ==============================================================

class SettingsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_from_env()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        router_group = QGroupBox("Router Settings")
        router_form = QFormLayout()

        self.router_url = QLineEdit()
        self.router_user = QLineEdit()
        self.router_pass = QLineEdit()
        self.router_pass.setEchoMode(QLineEdit.Password)

        router_form.addRow("Router URL:", self.router_url)
        router_form.addRow("Username:", self.router_user)
        router_form.addRow("Password:", self.router_pass)
        router_group.setLayout(router_form)

        isp_group = QGroupBox("ISP Settings")
        isp_form = QFormLayout()

        self.isp_login_url = QLineEdit()
        self.isp_cdr_url = QLineEdit()

        isp_form.addRow("Login URL:", self.isp_login_url)
        isp_form.addRow("CDR URL:", self.isp_cdr_url)
        isp_group.setLayout(isp_form)

        path_group = QGroupBox("Paths")
        path_form = QFormLayout()

        self.chrome_path = QLineEdit()
        self.tesseract_path = QLineEdit()

        path_form.addRow("Chrome:", self.chrome_path)
        path_form.addRow("Tesseract:", self.tesseract_path)
        path_group.setLayout(path_form)

        save_btn = QPushButton("💾 Save Settings to .env")
        save_btn.clicked.connect(self._save_to_env)

        layout.addWidget(router_group)
        layout.addWidget(isp_group)
        layout.addWidget(path_group)
        layout.addWidget(save_btn)
        layout.addStretch()

    def _load_from_env(self):
        if not ENV_PATH.exists():
            return
        values = dotenv_values(ENV_PATH)

        self.router_url.setText(values.get("ROUTER_URL", "") or "")
        self.router_user.setText(values.get("ROUTER_USERNAME", "") or "")
        self.router_pass.setText(values.get("ROUTER_PASSWORD", "") or "")
        self.isp_login_url.setText(values.get("ISP_LOGIN_URL", "") or "")
        self.isp_cdr_url.setText(values.get("ISP_CDR_URL", "") or "")
        self.chrome_path.setText(values.get("CHROME_PATH", "") or "")
        self.tesseract_path.setText(values.get("TESSERACT_CMD", "") or "")

    def _save_to_env(self):
        try:
            ENV_PATH.touch(exist_ok=True)
            set_key(str(ENV_PATH), "ROUTER_URL", self.router_url.text())
            set_key(str(ENV_PATH), "ROUTER_USERNAME", self.router_user.text())
            set_key(str(ENV_PATH), "ROUTER_PASSWORD", self.router_pass.text())
            set_key(str(ENV_PATH), "ISP_LOGIN_URL", self.isp_login_url.text())
            set_key(str(ENV_PATH), "ISP_CDR_URL", self.isp_cdr_url.text())
            set_key(str(ENV_PATH), "CHROME_PATH", self.chrome_path.text())
            set_key(str(ENV_PATH), "TESSERACT_CMD", self.tesseract_path.text())

            QMessageBox.information(
                self,
                "Saved",
                "Settings were saved successfully to .env.\n"
                "Restart the application for the changes to fully take effect.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed:\n{e}")


# ==============================================================
# Collection Tab
# ==============================================================

class CollectionTab(QWidget):
    def __init__(self, log_sink):
        super().__init__()
        self.log_sink = log_sink
        self._collector = None
        self._isp_worker = None
        self._analysis_worker = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        router_group = QGroupBox("Collect Data from Router")
        router_layout = QHBoxLayout()

        router_layout.addWidget(QLabel("Duration (hours):"))
        self.hours_spin = QSpinBox()
        self.hours_spin.setRange(1, 24)
        self.hours_spin.setValue(13)
        router_layout.addWidget(self.hours_spin)

        router_layout.addWidget(QLabel("Interval (seconds):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(30, 3600)
        self.interval_spin.setValue(600)
        router_layout.addWidget(self.interval_spin)

        self.start_btn = QPushButton("▶ Start Collection")
        self.start_btn.clicked.connect(self._start_collection)
        router_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_collection)
        router_layout.addWidget(self.stop_btn)

        router_layout.addStretch()
        router_group.setLayout(router_layout)

        isp_group = QGroupBox("AsiaTech Panel")
        isp_layout = QHBoxLayout()

        self.login_btn = QPushButton("🔐 Re-login / Save Session")
        self.login_btn.clicked.connect(self._open_login_dialog)
        isp_layout.addWidget(self.login_btn)

        self.isp_btn = QPushButton("🔄 Update ISP")
        self.isp_btn.clicked.connect(self._update_isp)
        isp_layout.addWidget(self.isp_btn)

        isp_layout.addStretch()
        isp_group.setLayout(isp_layout)

        analysis_group = QGroupBox("Analysis")
        analysis_layout = QHBoxLayout()

        self.analyze_btn = QPushButton("📊 Analyze + Train + Predict")
        self.analyze_btn.clicked.connect(self._run_analysis)
        analysis_layout.addWidget(self.analyze_btn)

        analysis_layout.addStretch()
        analysis_group.setLayout(analysis_layout)

        layout.addWidget(router_group)
        layout.addWidget(isp_group)
        layout.addWidget(analysis_group)
        layout.addStretch()

    def _start_collection(self):
        hours = self.hours_spin.value()
        interval = self.interval_spin.value()

        self._collector = RouterCollectorWorker(hours, interval)
        self._collector.log.connect(self.log_sink)
        self._collector.done.connect(self._on_collector_done)
        self._collector.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _stop_collection(self):
        if self._collector:
            self._collector.stop()

    def _on_collector_done(self, success: bool):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._collector = None

    def _open_login_dialog(self):
        dlg = IspLoginDialog(self)
        dlg.exec()

    def _update_isp(self):
        self._isp_worker = IspCollectorWorker()
        self._isp_worker.log.connect(self.log_sink)
        self._isp_worker.done.connect(
            lambda ok: self.log_sink(f"ISP update: {'✓' if ok else '✗'}")
        )
        self._isp_worker.start()
        self.isp_btn.setEnabled(False)
        self._isp_worker.finished.connect(
            lambda: self.isp_btn.setEnabled(True)
        )

    def _run_analysis(self):
        self._analysis_worker = AnalysisWorker()
        self._analysis_worker.log.connect(self.log_sink)
        self._analysis_worker.done.connect(
            lambda ok: self.log_sink(f"Analysis chain: {'✓' if ok else '✗'}")
        )
        self._analysis_worker.start()
        self.analyze_btn.setEnabled(False)
        self._analysis_worker.finished.connect(
            lambda: self.analyze_btn.setEnabled(True)
        )


# ==============================================================
# Dashboard Tab
# ==============================================================

class DashboardTab(QWidget):
    def __init__(self, log_sink=None):
        super().__init__()
        self.log_sink = log_sink
        self._usable = []        # cached list of usable samples
        self._model = None       # cached model
        self._selected_idx = -1  # index into self._usable (-1 = last)
        self._build_ui()
        self.refresh()

    def _log(self, msg: str):
        print(msg)
        if self.log_sink:
            self.log_sink(msg)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        container = QWidget()
        layout = QVBoxLayout(container)
        scroll.setWidget(container)

        # --- Top bar ---
        top = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.refresh)
        top.addWidget(refresh_btn)

        self.last_refresh_label = QLabel("")
        self.last_refresh_label.setStyleSheet("color: #888; font-style: italic;")
        top.addWidget(self.last_refresh_label)
        top.addStretch()
        layout.addLayout(top)

        # --- Summary ---
        self.summary_label = QLabel("...")
        self.summary_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        # --- Samples table (clickable) ---
        samples_group = QGroupBox(
            "📋 Usable Samples (click a row to see per-device predictions)"
        )
        samples_layout = QVBoxLayout()

        self.samples_table = QTableWidget(0, 8)
        self.samples_table.setHorizontalHeaderLabels(
            ["From", "To", "Duration (h)",
             "ISP use", "Pred use", "ISP ded", "Pred ded", "Error use"]
        )
        self.samples_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.samples_table.setMinimumHeight(220)
        self.samples_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.samples_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.samples_table.cellClicked.connect(self._on_sample_clicked)
        samples_layout.addWidget(self.samples_table)

        samples_group.setLayout(samples_layout)
        layout.addWidget(samples_group)

        # --- Per-device table ---
        self.device_group = QGroupBox("🤖 Per-device Predictions (selected sample)")
        device_layout = QVBoxLayout()

        self.selected_label = QLabel("—")
        self.selected_label.setStyleSheet("color: #555; font-style: italic;")
        self.selected_label.setWordWrap(True)
        device_layout.addWidget(self.selected_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["MAC", "Δtx", "Δrx", "Usage (GB)", "Deducted (GB)", "Share"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setMinimumHeight(180)
        device_layout.addWidget(self.table)

        self.device_group.setLayout(device_layout)
        layout.addWidget(self.device_group)

        # --- Live snapshot ---
        live_group = QGroupBox("📡 Live Status (last snapshot)")
        live_layout = QVBoxLayout()

        self.live_label = QLabel("...")
        self.live_label.setWordWrap(True)
        live_layout.addWidget(self.live_label)

        self.live_table = QTableWidget(0, 4)
        self.live_table.setHorizontalHeaderLabels(
            ["MAC", "tx_packet", "rx_packet", "tx_rate"]
        )
        self.live_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.live_table.setMaximumHeight(160)
        live_layout.addWidget(self.live_table)

        live_group.setLayout(live_layout)
        layout.addWidget(live_group)

        # --- Bar chart ---
        self.bar_plot = pg.PlotWidget()
        self.bar_plot.setTitle("Estimated Usage per Device (GB)")
        self.bar_plot.setBackground("w")
        self.bar_plot.setMinimumHeight(250)
        layout.addWidget(self.bar_plot)

        # --- Line chart ---
        self.line_plot = pg.PlotWidget()
        self.line_plot.setTitle("Total ISP Usage Trend (green=usage, red=deducted)")
        self.line_plot.setBackground("w")
        self.line_plot.setMinimumHeight(250)
        layout.addWidget(self.line_plot)

    # --- loading ---

    def _load_json(self, path):
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # --- refresh ---

    def refresh(self):
        try:
            self._log("\n[DASHBOARD] Refresh requested")

            model = self._load_json(MODEL_FILE)
            dataset = self._load_json(DATASET_FILE) or []
            isp = self._load_json(ISP_FILE) or []
            snapshots = load_snapshots()

            self._model = model
            self._usable = [s for s in dataset if s.get("router_delta_count", 0) > 0]

            self._log(
                f"[DASHBOARD] snapshots={len(snapshots)}, "
                f"dataset={len(dataset)}, isp={len(isp)}, "
                f"model={'✓' if model else '✗'}, "
                f"usable={len(self._usable)}"
            )

            self.last_refresh_label.setText(
                f"Last refresh: {_dt.now().strftime('%H:%M:%S')}"
            )

            last_snap_time = snapshots[-1]["timestamp"] if snapshots else "—"
            model_method = "?"
            if model and "usage" in model:
                model_method = model["usage"].get("method", "?")
            self.summary_label.setText(
                f"📸 snapshots: {len(snapshots)}   |   "
                f"last snapshot: {last_snap_time}\n"
                f"📊 dataset: {len(dataset)}   |   "
                f"usable: {len(self._usable)}   |   "
                f"ISP records: {len(isp)}   |   "
                f"model: {'✓ ' + model_method if model else '✗'}"
            )

            self._update_live_panel(snapshots, isp)
            self._update_samples_table()
            self._refresh_per_device_table()
            self._update_isp_trend(isp)

            self._log("[DASHBOARD] Refresh done ✓")

        except Exception as e:
            import traceback
            self._log(f"[DASHBOARD] ❌ ERROR: {e}")
            self._log(traceback.format_exc())

    # --- samples table ---

    def _update_samples_table(self):
        n = len(self._usable)
        self.samples_table.setRowCount(n)

        for row, s in enumerate(self._usable):
            actual_use = s.get("isp_usage_gb") or 0
            actual_ded = s.get("isp_deducted_gb") or 0

            pred_use = 0.0
            pred_ded = 0.0
            if self._model and "usage" in self._model:
                pred_use = predict_sample_total(s, self._model["usage"])
                pred_ded = predict_sample_total(s, self._model["deducted"])

            error_use = pred_use - actual_use

            self.samples_table.setItem(row, 0, QTableWidgetItem(s["isp_from"][5:16]))
            self.samples_table.setItem(row, 1, QTableWidgetItem(s["isp_to"][5:16]))
            self.samples_table.setItem(
                row, 2,
                QTableWidgetItem(f"{s.get('isp_duration_seconds', 0) / 3600:.2f}")
            )
            self.samples_table.setItem(row, 3, QTableWidgetItem(f"{actual_use:.3f}"))
            self.samples_table.setItem(row, 4, QTableWidgetItem(f"{pred_use:.3f}"))
            self.samples_table.setItem(row, 5, QTableWidgetItem(f"{actual_ded:.3f}"))
            self.samples_table.setItem(row, 6, QTableWidgetItem(f"{pred_ded:.3f}"))
            self.samples_table.setItem(row, 7, QTableWidgetItem(f"{error_use:+.3f}"))

        # Ensure selected index is valid
        if self._selected_idx < 0 or self._selected_idx >= n:
            self._selected_idx = n - 1 if n > 0 else -1

        if 0 <= self._selected_idx < n:
            self.samples_table.selectRow(self._selected_idx)

    def _on_sample_clicked(self, row: int, col: int):
        self._selected_idx = row
        self._refresh_per_device_table()

    # --- per-device table ---

    def _refresh_per_device_table(self):
        self.table.setRowCount(0)
        self.bar_plot.clear()

        if not self._usable or not self._model or "usage" not in self._model:
            self.selected_label.setText("— (no data or model available)")
            return

        idx = self._selected_idx
        if idx < 0 or idx >= len(self._usable):
            idx = len(self._usable) - 1

        sample = self._usable[idx]
        devices = sample.get("devices", [])

        self.selected_label.setText(
            f"Sample #{idx + 1} of {len(self._usable)}:   "
            f"{sample['isp_from'][5:16]} → {sample['isp_to'][5:16]}   |   "
            f"usage={(sample.get('isp_usage_gb') or 0):.3f} GB, "
            f"deducted={(sample.get('isp_deducted_gb') or 0):.3f} GB"
        )

        usage_by_mac = predict_devices(sample, self._model["usage"])
        ded_by_mac = predict_devices(sample, self._model["deducted"])

        rows = []
        for d in devices:
            rows.append((d, usage_by_mac.get(d["mac"], 0.0),
                         ded_by_mac.get(d["mac"], 0.0)))

        total_use = sum(u for _, u, _ in rows) or 1.0

        self.table.setRowCount(len(rows))
        for i, (d, u, dd) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(d.get("mac", "")))
            self.table.setItem(i, 1, QTableWidgetItem(f"{d.get('delta_tx_sum', 0):,}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{d.get('delta_rx_sum', 0):,}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{u:.4f}"))
            self.table.setItem(i, 4, QTableWidgetItem(f"{dd:.4f}"))
            self.table.setItem(i, 5, QTableWidgetItem(f"{u/total_use:.1%}"))

        # Bar chart for this sample
        macs = [d["mac"][-5:] for d, _, _ in rows]
        usages = [u for _, u, _ in rows]
        self.bar_plot.addItem(
            pg.BarGraphItem(
                x=list(range(len(usages))),
                height=usages,
                width=0.6,
                brush="#3b82f6",
            )
        )
        ax = self.bar_plot.getAxis("bottom")
        ax.setTicks([[(i, m) for i, m in enumerate(macs)]])

    # --- live panel ---

    def _update_live_panel(self, snapshots, isp_records):
        if not snapshots:
            self.live_label.setText("No snapshots available.")
            self.live_table.setRowCount(0)
            return

        last_snap = snapshots[-1]
        prev_snap = snapshots[-2] if len(snapshots) >= 2 else None
        last_time = last_snap["timestamp"]
        n_devices = len(last_snap["users"])

        gap_txt = ""
        if prev_snap:
            t1 = _dt.fromisoformat(prev_snap["timestamp"])
            t2 = _dt.fromisoformat(last_time)
            gap_txt = f"   |   gap from previous: {int((t2 - t1).total_seconds())} s"

        if isp_records:
            last_isp_to = max(r["to"] for r in isp_records)
            if last_time <= last_isp_to:
                coverage_txt = "✅ Last snapshot is inside the ISP window"
            else:
                coverage_txt = (
                    f"⚠ Last snapshot is after the last ISP record "
                    f"({last_isp_to}) — ISP update needed"
                )
        else:
            coverage_txt = "⚠ No ISP records saved"

        self.live_label.setText(
            f"Last snapshot: {last_time}\n"
            f"Device count: {n_devices}{gap_txt}\n"
            f"{coverage_txt}"
        )

        users = last_snap.get("users", [])
        self.live_table.setRowCount(len(users))
        for row, u in enumerate(users):
            self.live_table.setItem(row, 0, QTableWidgetItem(u.get("mac", "")))
            self.live_table.setItem(
                row, 1, QTableWidgetItem(f"{u.get('tx_packet', 0):,}")
            )
            self.live_table.setItem(
                row, 2, QTableWidgetItem(f"{u.get('rx_packet', 0):,}")
            )
            self.live_table.setItem(
                row, 3, QTableWidgetItem(str(u.get("tx_rate", "")))
            )

    # --- ISP trend chart ---

    def _update_isp_trend(self, isp_records):
        self.line_plot.clear()
        if not isp_records:
            return

        records = sorted(isp_records, key=lambda r: r["from"])
        x = list(range(len(records)))
        y_use = [r.get("usage_gb") or 0 for r in records]
        y_ded = [r.get("deducted_gb") or 0 for r in records]

        self.line_plot.plot(x, y_use, pen="g", symbol="o")
        if any(v > 0 for v in y_ded):
            self.line_plot.plot(x, y_ded, pen="r", symbol="t")

        ax = self.line_plot.getAxis("bottom")
        labels = [r["from"][5:16] for r in records]
        ax.setTicks([[(i, l) for i, l in enumerate(labels)]])


# ==============================================================
# Main Window
# ==============================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Internet Usage Agent")
        self.resize(1200, 850)

        central = QWidget()
        layout = QVBoxLayout(central)

        self.tabs = QTabWidget()

        # --- log_box FIRST (so log_sink works during tab construction) ---
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(200)

        # Now safe to build tabs
        self.settings_tab = SettingsTab()
        self.collection_tab = CollectionTab(log_sink=self._append_log)
        self.dashboard_tab = DashboardTab(log_sink=self._append_log)

        self.tabs.addTab(self.settings_tab, "⚙ Settings")
        self.tabs.addTab(self.collection_tab, "📡 Data Collection")
        self.tabs.addTab(self.dashboard_tab, "📊 Dashboard")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self.tabs, stretch=2)
        layout.addWidget(QLabel("Operation Log:"))
        layout.addWidget(self.log_box, stretch=1)

        self.setCentralWidget(central)

    def _append_log(self, text: str):
        self.log_box.append(text)

    def _on_tab_changed(self, idx: int):
        if self.tabs.widget(idx) is self.dashboard_tab:
            self.dashboard_tab.refresh()