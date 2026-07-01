import sys
import csv
import os
import argparse
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QPushButton, QFileDialog, QLineEdit,
    QCheckBox, QComboBox, QSizePolicy
)

class DataViewerUI(QMainWindow):
    def __init__(self, filepath=None):
        super().__init__()
        self.setWindowTitle("UART Data Viewer")
        self.resize(1000, 650)

        self.channel_data = {}       # label -> np.ndarray of values
        self.channel_labels = []
        self.time_seconds = None     # np.ndarray of seconds from start, or None
        self.channel_curves = {}     # label -> PlotDataItem
        self.channel_checkboxes = {} # label -> QCheckBox
        self.autoscale = True

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # File picker row
        row_file = QHBoxLayout()
        self.file_label = QLabel("No file loaded")
        self.file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row_file.addWidget(self.file_label)
        open_btn = QPushButton("Open CSV…")
        open_btn.clicked.connect(self.open_file)
        row_file.addWidget(open_btn)
        root.addLayout(row_file)

        # Info row
        self.info_label = QLabel("")
        root.addWidget(self.info_label)

        # Controls row
        row_ctrl = QHBoxLayout()
        row_ctrl.addWidget(QLabel("X Axis:"))
        self.xaxis_combo = QComboBox()
        self.xaxis_combo.addItems(["Sample Index", "Time (s)"])
        self.xaxis_combo.currentIndexChanged.connect(self.update_plot)
        row_ctrl.addWidget(self.xaxis_combo)
        row_ctrl.addSpacing(20)
        row_ctrl.addWidget(QLabel("Y Min:"))
        self.ymin_input = QLineEdit("")
        self.ymin_input.setMaximumWidth(80)
        self.ymin_input.editingFinished.connect(self.apply_y_limits)
        row_ctrl.addWidget(self.ymin_input)
        row_ctrl.addWidget(QLabel("Y Max:"))
        self.ymax_input = QLineEdit("")
        self.ymax_input.setMaximumWidth(80)
        self.ymax_input.editingFinished.connect(self.apply_y_limits)
        row_ctrl.addWidget(self.ymax_input)
        self.autoscale_btn = QPushButton("Autoscale: On")
        self.autoscale_btn.setCheckable(True)
        self.autoscale_btn.setChecked(True)
        self.autoscale_btn.clicked.connect(self.toggle_autoscale)
        row_ctrl.addWidget(self.autoscale_btn)
        row_ctrl.addStretch()
        root.addLayout(row_ctrl)

        # Plot
        self.graph = pg.PlotWidget()
        self.graph.setBackground('w')
        self.graph.setTitle("UART Data Viewer", color="k", size="14pt")
        self.graph.setLabel('left', 'Value', color='k')
        self.graph.setLabel('bottom', 'Sample', color='k')
        self.graph.showGrid(x=True, y=True)
        self.legend = self.graph.addLegend(offset=(10, 10))
        root.addWidget(self.graph)

        # Channel checkbox row (populated after load)
        self.ch_row = QHBoxLayout()
        self.ch_row.addWidget(QLabel("Channels:"))
        self.ch_row.addStretch()
        root.addLayout(self.ch_row)

        if filepath and os.path.isfile(filepath):
            self.load_csv(filepath)

    def open_file(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_dir = os.path.join(script_dir, 'data')
        if not os.path.isdir(default_dir):
            default_dir = script_dir
        path, _ = QFileDialog.getOpenFileName(
            self, "Open CSV File", default_dir, "CSV Files (*.csv);;All Files (*)"
        )
        if path:
            self.load_csv(path)

    def load_csv(self, path):
        try:
            with open(path, newline='', encoding='utf-8-sig') as f:
                all_rows = list(csv.reader(f))
        except Exception as e:
            self.info_label.setText(f"Cannot read file: {e}")
            return

        if not all_rows:
            self.info_label.setText("File is empty.")
            return

        def is_numeric(s):
            try:
                float(s)
                return True
            except Exception:
                return False

        header = [s.strip() for s in all_rows[0]]
        has_timestamp = bool(header) and header[0].lower() in ('timestamp', 'time', 't')

        if has_timestamp:
            labels = header[1:]
            data_rows = all_rows[1:]
        elif any(not is_numeric(c) for c in header if c):
            labels = header
            data_rows = all_rows[1:]
        else:
            labels = [f'chan{i+1}' for i in range(len(header))]
            data_rows = all_rows

        if not labels:
            self.info_label.setText("No data columns found.")
            return

        n_col = len(labels)
        times_raw = []
        ch_lists = [[] for _ in labels]

        for row in data_rows:
            if not row:
                continue
            try:
                if has_timestamp:
                    times_raw.append(row[0].strip())
                    vals = row[1:n_col + 1]
                else:
                    vals = row[:n_col]

                floats = [float(v.strip()) if v.strip() else float('nan') for v in vals]
                while len(floats) < n_col:
                    floats.append(float('nan'))
                for i, v in enumerate(floats[:n_col]):
                    ch_lists[i].append(v)
            except (ValueError, IndexError):
                continue

        self.channel_labels = labels
        self.channel_data = {lbl: np.array(ch_lists[i]) for i, lbl in enumerate(labels)}

        self.time_seconds = None
        if has_timestamp and times_raw:
            ts_epoch = []
            for ts in times_raw:
                try:
                    dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S.%f')
                    ts_epoch.append(dt.timestamp())
                except Exception:
                    ts_epoch.append(float('nan'))
            arr = np.array(ts_epoch, dtype=float)
            valid = arr[~np.isnan(arr)]
            if len(valid):
                self.time_seconds = arr - valid[0]

        n = max((len(v) for v in self.channel_data.values()), default=0)
        dur_str = ""
        if self.time_seconds is not None:
            valid = self.time_seconds[~np.isnan(self.time_seconds)]
            if len(valid) > 1:
                dur_str = f" | Duration: {valid[-1] - valid[0]:.3f} s"

        self.file_label.setText(os.path.basename(path))
        self.info_label.setText(f"{n} samples | {len(labels)} channel(s){dur_str}")
        self.setWindowTitle(f"UART Data Viewer — {os.path.basename(path)}")

        self._rebuild_curves()
        self.update_plot()

    def _rebuild_curves(self):
        self.graph.clear()
        try:
            self.legend.clear()
        except Exception:
            pass
        self.legend = self.graph.addLegend(offset=(10, 10))
        self.channel_curves = {}

        for cb in list(self.channel_checkboxes.values()):
            self.ch_row.removeWidget(cb)
            cb.deleteLater()
        self.channel_checkboxes = {}

        for i, lbl in enumerate(self.channel_labels):
            pen = pg.mkPen(color=pg.intColor(i), width=2)
            curve = self.graph.plot(pen=pen, name=lbl)
            self.channel_curves[lbl] = curve

            cb = QCheckBox(lbl)
            cb.setChecked(True)
            r, g, b, _ = pg.intColor(i).getRgb()
            cb.setStyleSheet(f"color: rgb({r},{g},{b}); font-weight: bold;")
            cb.stateChanged.connect(self.update_plot)
            self.channel_checkboxes[lbl] = cb
            self.ch_row.insertWidget(self.ch_row.count() - 1, cb)

    def update_plot(self):
        if not self.channel_data:
            return

        use_time = (self.xaxis_combo.currentText() == "Time (s)"
                    and self.time_seconds is not None)
        self.graph.setLabel('bottom', 'Time (s)' if use_time else 'Sample', color='k')

        for lbl, curve in self.channel_curves.items():
            cb = self.channel_checkboxes.get(lbl)
            if cb and not cb.isChecked():
                curve.setVisible(False)
                continue
            curve.setVisible(True)
            y = self.channel_data.get(lbl, np.array([]))
            if use_time:
                n = min(len(self.time_seconds), len(y))
                curve.setData(self.time_seconds[:n], y[:n])
            else:
                curve.setData(y)

        if self.autoscale:
            self.graph.enableAutoRange()
        else:
            self.apply_y_limits()

    def toggle_autoscale(self):
        self.autoscale = self.autoscale_btn.isChecked()
        self.autoscale_btn.setText(f"Autoscale: {'On' if self.autoscale else 'Off'}")
        if self.autoscale:
            self.graph.enableAutoRange()
        else:
            self.apply_y_limits()

    def apply_y_limits(self):
        try:
            ymin = float(self.ymin_input.text().strip())
            ymax = float(self.ymax_input.text().strip())
            if ymax > ymin:
                self.graph.setYRange(ymin, ymax)
        except Exception:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='UART Data Viewer - Visualize recorded CSV data'
    )
    parser.add_argument('file', nargs='?', help='CSV file to open on launch')
    args = parser.parse_args()

    app = QApplication(sys.argv)
    window = DataViewerUI(filepath=args.file)
    window.show()
    sys.exit(app.exec_())
