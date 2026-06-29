import sys
import csv
import time
import os
import serial
import threading
import argparse
from datetime import datetime
from collections import deque

import pyqtgraph as pg
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, 
                             QWidget, QLineEdit, QLabel, QHBoxLayout,
                             QPushButton, QFileDialog, QSizePolicy, QDialog, QMessageBox)
from PyQt5.QtCore import QTimer

# --- Configuration ---
SERIAL_PORT = 'COM5'       # Default COM port; can be overridden from command line
BAUD_RATE = 921600
LOG_FILE = 'live_uart_data.csv'
MAX_HISTORY = 10000        # Maximum samples to hold in RAM
# ---------------------

class DataLoggerUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Live UART Data Plotter")
        self.resize(800, 600)

        # 1. Data Structures
        # Support multiple data channels: a list of deques (one per channel)
        self.channel_buffers = []  # list of deque(maxlen=MAX_HISTORY)
        self.n_channels = None
        self.plot_curves = []
        self.channel_labels = []
        self.window_size = 100 # Default X-axis sample width
        # Logging state: default to a `data` folder next to this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_dir = os.path.join(script_dir, 'data')
        try:
            os.makedirs(self.log_dir, exist_ok=True)
        except Exception:
            pass
        self.recording = False
        self.log_file = None
        self.log_writer = None

        # 2. UI Setup
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Top Controls Layout (first row: sample width)
        self.control_layout = QHBoxLayout()
        self.layout.addLayout(self.control_layout)

        self.label = QLabel("X-Axis Sample Width:")
        self.control_layout.addWidget(self.label)

        # Text field for window size
        self.width_input = QLineEdit(str(self.window_size))
        self.width_input.textChanged.connect(self.update_window_size)
        self.control_layout.addWidget(self.width_input)
        self.control_layout.addStretch()

        # Fourth row: Y-axis controls (min, max, autoscale)
        self.y_layout = QHBoxLayout()
        self.layout.addLayout(self.y_layout)
        self.ymin_label = QLabel("Y Min:")
        self.y_layout.addWidget(self.ymin_label)
        self.ymin_input = QLineEdit("")
        self.ymin_input.setMaximumWidth(120)
        self.y_layout.addWidget(self.ymin_input) 
        self.ymax_label = QLabel("Y Max:")
        self.y_layout.addWidget(self.ymax_label)
        self.ymax_input = QLineEdit("")
        self.ymax_input.setMaximumWidth(120)
        self.y_layout.addWidget(self.ymax_input)
        self.autoscale_button = QPushButton("Autoscale: On")
        self.autoscale_button.setCheckable(True)
        self.autoscale_button.setChecked(True)
        self.autoscale_button.clicked.connect(self.toggle_autoscale)
        self.y_layout.addWidget(self.autoscale_button)
        self.y_layout.addStretch()

        # Y-axis state
        self.autoscale = True
        # apply edits when user finishes typing
        self.ymin_input.editingFinished.connect(self.apply_y_limits)
        self.ymax_input.editingFinished.connect(self.apply_y_limits)

        # Second row: directory chooser
        self.dir_layout = QHBoxLayout()
        self.layout.addLayout(self.dir_layout)
        # Indicator + current output directory, then chooser button
        self.dir_label_indicator = QLabel("Output Directory:")
        self.dir_layout.addWidget(self.dir_label_indicator)
        # Make the directory editable so users can paste paths directly
        self.dir_input = QLineEdit(self.log_dir)
        self.dir_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.dir_layout.addWidget(self.dir_input, 1)
        self.choose_dir_button = QPushButton("Choose Directory")
        self.choose_dir_button.clicked.connect(self.choose_directory)
        self.dir_layout.addWidget(self.choose_dir_button)
        self.dir_layout.addStretch()

        # Third row: filename and recording controls
        self.file_layout = QHBoxLayout()
        self.layout.addLayout(self.file_layout)
        # Filename input (user can type desired filename before recording)
        self.filename_label = QLabel("Filename:")
        self.file_layout.addWidget(self.filename_label)
        # Make both labels the same width so the inputs' left edges align
        try:
            label_w = max(self.dir_label_indicator.sizeHint().width(), self.filename_label.sizeHint().width())
            self.dir_label_indicator.setFixedWidth(label_w)
            self.filename_label.setFixedWidth(label_w)
        except Exception:
            pass
        self.filename_input = QLineEdit(LOG_FILE)
        self.filename_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.file_layout.addWidget(self.filename_input, 1)
        self.start_button = QPushButton("Start Recording")
        self.start_button.clicked.connect(self.start_recording)
        self.file_layout.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop Recording")
        self.stop_button.clicked.connect(self.stop_recording)
        self.stop_button.setEnabled(False)
        self.file_layout.addWidget(self.stop_button)
        self.file_layout.addStretch()
        

        # 3. Plot Setup
        self.graph = pg.PlotWidget()
        self.graph.setBackground('w')
        self.graph.setTitle(f"Live UART Stream - {SERIAL_PORT}", color="k", size="14pt")
        self.graph.setLabel('left', 'Value', color='k')
        self.graph.setLabel('bottom', 'Samples', color='k')
        self.graph.showGrid(x=True, y=True)
        self.layout.addWidget(self.graph)
        
        # No fixed curve yet — curves are created dynamically when data arrives
        self.graph.addLegend(offset=(10, 10))

        # Buttons below the plot: edit labels + reset
        self.buttons_row = QHBoxLayout()
        self.edit_labels_button = QPushButton("Edit Channel Labels")
        self.edit_labels_button.clicked.connect(self.edit_channel_labels)
        self.buttons_row.addWidget(self.edit_labels_button)
        self.reset_button = QPushButton("Reset Data/Channels")
        self.reset_button.clicked.connect(self.reset_all)
        self.buttons_row.addWidget(self.reset_button)
        self.buttons_row.addStretch()
        self.layout.addLayout(self.buttons_row)

        # 4. Serial & Thread Setup
        self.running = True
        try:
            self.serial_port = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        except serial.SerialException as e:
            print(f"Failed to connect to {SERIAL_PORT}: {e}")
            sys.exit(1)

        # Start the background data reading thread (does not open files)
        self.thread = threading.Thread(target=self.read_and_log_serial, daemon=True)
        self.thread.start()

        # 5. UI Update Timer
        # Updates the graph 20 times per second (50ms) without blocking
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(50) 

    def update_window_size(self, text):
        """Called automatically whenever the text field changes."""
        try:
            val = int(text)
            if val > 0: # Allow any positive window size
                self.window_size = val
        except ValueError:
            pass # Ignore invalid text (e.g., letters)

    def read_and_log_serial(self):
        """Runs in a background thread to prevent UI freezing."""
        while self.running:
            if self.serial_port.in_waiting:
                raw_bytes = self.serial_port.readline()
                try:
                    decoded_line = raw_bytes.decode('utf-8').strip()

                    if decoded_line:
                        # Parse comma-separated values (any number of channels)
                        parts = [p.strip() for p in decoded_line.split(',') if p.strip() != '']
                        vals = []
                        try:
                            for p in parts:
                                vals.append(float(p))
                        except ValueError:
                            # If any value can't be parsed, skip the whole line
                            continue

                        # Initialize channel buffers and curves on first valid line
                        if self.n_channels is None:
                            self.n_channels = len(vals)
                        # If more channels appear, expand buffers/curves
                        if len(vals) > (self.n_channels or 0):
                            self.n_channels = len(vals)

                        # Ensure channel_buffers length matches n_channels
                        if len(self.channel_buffers) < self.n_channels:
                            # create additional deques and plot curves
                            start_idx = len(self.channel_buffers)
                            for i in range(start_idx, self.n_channels):
                                dq = deque(maxlen=MAX_HISTORY)
                                self.channel_buffers.append(dq)
                                # ensure a default label exists for this channel
                                label = f'chan{i+1}'
                                self.channel_labels.append(label)
                                # create a new curve with unique color and legend label
                                pen = pg.mkPen(color=pg.intColor(i), width=2)
                                curve = self.graph.plot(pen=pen, name=label)
                                self.plot_curves.append(curve)

                        # If fewer values than channels, pad with nan so buffers stay aligned
                        if len(vals) < self.n_channels:
                            vals.extend([float('nan')] * (self.n_channels - len(vals)))

                        # Append values to each channel buffer
                        for i, v in enumerate(vals[:self.n_channels]):
                            try:
                                self.channel_buffers[i].append(v)
                            except Exception:
                                pass

                        # Log to CSV only when recording is active
                        if self.recording and self.log_writer and self.log_file:
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                            try:
                                # write header lazily if needed
                                if not getattr(self, 'header_written', False):
                                    # If file was non-empty when opened, assume header already present
                                    # Otherwise write a header based on current channel count
                                    header = ['timestamp'] + [self.channel_labels[i] if i < len(self.channel_labels) else f'chan{i+1}' for i in range(self.n_channels or len(vals))]
                                    try:
                                        self.log_writer.writerow(header)
                                        self.log_file.flush()
                                    except Exception:
                                        pass
                                    self.header_written = True

                                row = [timestamp] + [('' if (v is None or (isinstance(v, float) and str(v) == 'nan')) else v) for v in vals[:self.n_channels]]
                                self.log_writer.writerow(row)
                                self.log_file.flush()
                            except Exception:
                                # If writing fails for any reason, stop recording to be safe
                                self.stop_recording()

                except (UnicodeDecodeError, ValueError):
                    # Ignores corrupted bytes or non-numeric lines 
                    pass

    def update_plot(self):
        """Pulls the latest data slice and updates the graph."""
        if not self.channel_buffers:
            return

        # Update each channel's curve
        for i, buf in enumerate(self.channel_buffers):
            data = list(buf)
            if len(data) > self.window_size:
                data = data[-self.window_size:]
            try:
                # replace nan with None so pyqtgraph can handle gaps
                self.plot_curves[i].setData(data)
            except Exception:
                pass

        # Apply Y-axis limits if autoscale is disabled
        if not getattr(self, 'autoscale', True):
            if self.validate_y_limits():
                ymin, ymax = self.parse_y_limits()
                if ymin is not None and ymax is not None and ymax > ymin:
                    try:
                        self.graph.setYRange(ymin, ymax)
                    except Exception:
                        pass
        else:
            try:
                self.graph.enableAutoRange()
            except Exception:
                pass

    def closeEvent(self, event):
        """Ensures the serial port and thread close cleanly when the 'X' is clicked."""
        self.running = False
        # Stop recording and close file if open
        if self.recording:
            self.stop_recording()

        try:
            self.serial_port.close()
        except Exception:
            pass
        event.accept()

    def choose_directory(self):
        """Opens a folder chooser and updates the display label."""
        selected = QFileDialog.getExistingDirectory(self, "Select Log Directory", self.log_dir)
        if selected:
            self.log_dir = selected
            # update the editable field so users can copy/paste or edit further
            self.dir_input.setText(self.log_dir)

    def edit_channel_labels(self):
        """Open a dialog allowing the user to edit channel labels."""
        if not self.n_channels:
            QMessageBox.information(self, "No channels", "No channels detected yet. Wait for data or start recording.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Channel Labels")
        dlg_layout = QVBoxLayout(dialog)
        edits = []
        for i in range(self.n_channels):
            row = QHBoxLayout()
            lbl = QLabel(f"Channel {i+1}:")
            le = QLineEdit(self.channel_labels[i] if i < len(self.channel_labels) else f'chan{i+1}')
            le.setMinimumWidth(200)
            row.addWidget(lbl)
            row.addWidget(le)
            dlg_layout.addLayout(row)
            edits.append(le)

        btn_row = QHBoxLayout()
        import_btn = QPushButton("Import from CSV")
        btn_row.addWidget(import_btn)
        btn_row.addStretch()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        dlg_layout.addLayout(btn_row)

        save_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)

        def on_import():
            filename, _ = QFileDialog.getOpenFileName(self, "Select CSV File", self.log_dir, "CSV Files (*.csv);;All Files (*)")
            if not filename:
                return
            try:
                with open(filename, newline='') as fh:
                    rdr = csv.reader(fh)
                    first = next(rdr, None)
                    if first is None:
                        QMessageBox.warning(self, "Empty file", "Selected CSV is empty.")
                        return
                    hdr = [s.strip() for s in first]
                    # If first column is timestamp, drop it
                    if hdr and hdr[0].lower() in ('timestamp', 'time', 't'):
                        labels = hdr[1:]
                    else:
                        # Decide whether first row is header (non-numeric tokens) or data
                        is_header = False
                        for cell in hdr:
                            try:
                                float(cell)
                            except Exception:
                                is_header = True
                                break
                        if is_header:
                            labels = hdr
                        else:
                            # numeric row: use column count to build default labels
                            labels = [f'chan{i+1}' for i in range(len(hdr))]

                    # Apply labels and adjust channel/curve counts
                    new_n = len(labels)
                    # If channels already detected, ignore any imported labels for channels we don't have
                    if self.n_channels is not None and new_n > self.n_channels:
                        labels = labels[:self.n_channels]
                        new_n = self.n_channels

                    if self.n_channels is None:
                        # No channels detected yet: adopt imported label count
                        self.n_channels = new_n

                    # expand buffers/curves if needed (only up to new_n)
                    if len(self.channel_buffers) < new_n:
                        start_idx = len(self.channel_buffers)
                        for i in range(start_idx, new_n):
                            dq = deque(maxlen=MAX_HISTORY)
                            self.channel_buffers.append(dq)
                            label = f'chan{i+1}'
                            self.channel_labels.append(label)
                            pen = pg.mkPen(color=pg.intColor(i), width=2)
                            curve = self.graph.plot(pen=pen, name=label)
                            self.plot_curves.append(curve)

                    # If existing labels present and new labels are a permutation, reorder buffers/curves
                    if self.channel_labels:
                        mapping = {lbl: idx for idx, lbl in enumerate(self.channel_labels)}
                        if all(lbl in mapping for lbl in labels):
                            new_buffers = []
                            new_curves = []
                            for lbl in labels:
                                idx = mapping[lbl]
                                new_buffers.append(self.channel_buffers[idx])
                                new_curves.append(self.plot_curves[idx])
                            self.channel_buffers = new_buffers
                            self.plot_curves = new_curves

                    # Finally set labels and refresh legend
                    self.channel_labels = labels[:]
                    self.n_channels = len(self.channel_labels)
                    # If the dialog has fewer edit fields than new labels, insert rows
                    try:
                        btn_index = dlg_layout.count() - 1
                        if btn_index < 0:
                            btn_index = dlg_layout.count()
                        if len(edits) < self.n_channels:
                            for j in range(len(edits), self.n_channels):
                                row = QHBoxLayout()
                                lblw = QLabel(f"Channel {j+1}:")
                                lew = QLineEdit(self.channel_labels[j] if j < len(self.channel_labels) else f'chan{j+1}')
                                lew.setMinimumWidth(200)
                                row.addWidget(lblw)
                                row.addWidget(lew)
                                dlg_layout.insertLayout(btn_index, row)
                                edits.append(lew)
                                btn_index += 1
                    except Exception:
                        pass

                    # Update existing edit fields to reflect imported labels
                    for i, le in enumerate(edits):
                        try:
                            le.setText(self.channel_labels[i] if i < len(self.channel_labels) else '')
                        except Exception:
                            pass

                    self.update_legend_labels()
                    QMessageBox.information(self, "Imported", f"Imported {len(self.channel_labels)} labels from CSV.")
            except Exception as e:
                QMessageBox.warning(self, "Import failed", f"Failed to read CSV: {e}")

        import_btn.clicked.connect(on_import)

        if dialog.exec_() == QDialog.Accepted:
            limit = self.n_channels if self.n_channels is not None else len(edits)
            for i in range(limit):
                le = edits[i] if i < len(edits) else None
                lbl_text = (le.text().strip() if (le is not None) else '') or f'chan{i+1}'
                if i < len(self.channel_labels):
                    self.channel_labels[i] = lbl_text
                else:
                    self.channel_labels.append(lbl_text)
            # ignore any extra edit fields beyond detected channels
            self.update_legend_labels()

    def reset_all(self):
        """Clear all in-memory data, reset detected channels, and optionally clear CSV files."""
        resp = QMessageBox.question(self, "Reset All", "This will clear all in-memory data and reset detected channels. Continue?", QMessageBox.Yes | QMessageBox.No)
        if resp != QMessageBox.Yes:
            return

        # Stop and close recording if active
        try:
            if self.recording:
                self.stop_recording()
        except Exception:
            pass

        # Clear buffers
        try:
            self.channel_buffers = []
        except Exception:
            self.channel_buffers = []
        self.n_channels = None

        # Clear plot and legend, then recreate legend area
        try:
            self.graph.clear()
        except Exception:
            pass
        try:
            self.plot_curves = []
            self.channel_labels = []
            self.graph.addLegend(offset=(10, 10))
        except Exception:
            pass

        # Do NOT modify recorded CSV files — preserve all recorded data on disk.
        QMessageBox.information(self, "Reset", "In-memory data and channels have been reset.")

    def update_legend_labels(self):
        """Refresh the plot legend to reflect `self.channel_labels`."""
        try:
            legend = getattr(self.graph.plotItem, 'legend', None)
            if legend is None:
                self.graph.addLegend(offset=(10, 10))
                legend = self.graph.plotItem.legend
            else:
                try:
                    legend.clear()
                except Exception:
                    pass

            for i, curve in enumerate(self.plot_curves):
                label = self.channel_labels[i] if i < len(self.channel_labels) else f'chan{i+1}'
                try:
                    legend.addItem(curve, label)
                except Exception:
                    pass
        except Exception:
            pass

    def parse_y_limits(self):
        """Return (ymin, ymax) floats or (None, None) if invalid."""
        try:
            tmin = self.ymin_input.text().strip()
            tmax = self.ymax_input.text().strip()
            if not tmin or not tmax:
                return (None, None)
            ymin = float(tmin)
            ymax = float(tmax)
            return (ymin, ymax)
        except Exception:
            return (None, None)

    def apply_y_limits(self):
        """Apply Y limits immediately if autoscale is off."""
        if not getattr(self, 'autoscale', True):
            if self.validate_y_limits():
                ymin, ymax = self.parse_y_limits()
                if ymin is not None and ymax is not None and ymax > ymin:
                    try:
                        self.graph.setYRange(ymin, ymax)
                    except Exception:
                        pass

    def toggle_autoscale(self):
        """Toggle autoscaling on/off and update button text."""
        self.autoscale = self.autoscale_button.isChecked()
        self.autoscale_button.setText(f"Autoscale: {'On' if self.autoscale else 'Off'}")
        if self.autoscale:
            try:
                self.graph.enableAutoRange()
            except Exception:
                pass
        else:
            # apply existing fields immediately
            self.apply_y_limits()

    def validate_y_limits(self):
        """Validate Y min/max and visually mark inputs when invalid.
        
        Returns True if valid (both present, numeric, and min < max), else False.
        """
        tmin = self.ymin_input.text().strip()
        tmax = self.ymax_input.text().strip()
        invalid_style = "background-color: #ffcccc"
        normal_style = ""
        try:
            if not tmin or not tmax:
                # clear any previous styling
                self.ymin_input.setStyleSheet(normal_style)
                self.ymax_input.setStyleSheet(normal_style)
                return False
            ymin = float(tmin)
            ymax = float(tmax)
            if ymin >= ymax:
                # mark both fields as invalid
                self.ymin_input.setStyleSheet(invalid_style)
                self.ymax_input.setStyleSheet(invalid_style)
                return False
            else:
                self.ymin_input.setStyleSheet(normal_style)
                self.ymax_input.setStyleSheet(normal_style)
                return True
        except Exception:
            # non-numeric
            self.ymin_input.setStyleSheet(invalid_style)
            self.ymax_input.setStyleSheet(invalid_style)
            return False

    def start_recording(self):
        """Open the CSV file for appending in the selected directory."""
        if self.recording:
            return

        try:
            # Read directory from the editable field (allow user to paste)
            dir_text = (self.dir_input.text().strip() if hasattr(self, 'dir_input') else '')
            if dir_text:
                target_dir = dir_text
            else:
                target_dir = self.log_dir

            os.makedirs(target_dir, exist_ok=True)
            # Use filename provided by user, sanitize and ensure .csv
            name = (self.filename_input.text().strip() if hasattr(self, 'filename_input') else '')
            if not name:
                name = LOG_FILE
            # remove any path components for safety
            name = os.path.basename(name)
            if not name.lower().endswith('.csv'):
                name = name + '.csv'
            path = os.path.join(target_dir, name)
            # If the file already exists, ask the user whether to overwrite, append, or cancel
            mode = 'a'
            existing_labels = None
            if os.path.exists(path):
                # Read first row to detect header/column count
                try:
                    if os.path.getsize(path) > 0:
                        with open(path, newline='') as fh:
                            rdr = csv.reader(fh)
                            first = next(rdr, None)
                            if first is not None:
                                hdr = [s.strip() for s in first]
                                if hdr and hdr[0].lower() in ('timestamp', 'time', 't'):
                                    existing_labels = hdr[1:]
                                else:
                                    # determine if header or numeric row
                                    is_header = False
                                    for cell in hdr:
                                        try:
                                            float(cell)
                                        except Exception:
                                            is_header = True
                                            break
                                    if is_header:
                                        existing_labels = hdr
                                    else:
                                        existing_labels = [f'chan{i+1}' for i in range(len(hdr))]
                except Exception:
                    existing_labels = None

                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Warning)
                msg.setWindowTitle("File Exists")
                msg.setText(f"The file '{name}' already exists in the selected directory.")
                info = "Choose whether to overwrite the file, append to it, or cancel recording."
                if existing_labels:
                    info += f"\nDetected existing columns: {len(existing_labels)}"
                msg.setInformativeText(info)
                overwrite_btn = msg.addButton('Overwrite', QMessageBox.AcceptRole)
                append_btn = msg.addButton('Append', QMessageBox.AcceptRole)
                cancel_btn = msg.addButton('Cancel', QMessageBox.RejectRole)
                msg.exec_()
                clicked = msg.clickedButton()
                if clicked == cancel_btn:
                    return
                elif clicked == overwrite_btn:
                    mode = 'w'
                else:
                    mode = 'a'

            # If appending to an existing file with a header, compare column counts
            if mode == 'a' and existing_labels:
                file_n = len(existing_labels)
                if self.n_channels is None:
                    # adopt labels and channel count from the existing file
                    self.n_channels = file_n
                    self.channel_labels = existing_labels[:]
                    # ensure buffers/curves exist for these channels
                    if len(self.channel_buffers) < self.n_channels:
                        start_idx = len(self.channel_buffers)
                        for i in range(start_idx, self.n_channels):
                            dq = deque(maxlen=MAX_HISTORY)
                            self.channel_buffers.append(dq)
                            label = self.channel_labels[i] if i < len(self.channel_labels) else f'chan{i+1}'
                            pen = pg.mkPen(color=pg.intColor(i), width=2)
                            curve = self.graph.plot(pen=pen, name=label)
                            self.plot_curves.append(curve)
                    self.update_legend_labels()
                elif self.n_channels != file_n:
                    # mismatch: ask user whether to overwrite, append anyway, or cancel
                    msg2 = QMessageBox(self)
                    msg2.setIcon(QMessageBox.Warning)
                    msg2.setWindowTitle("Column Mismatch")
                    msg2.setText(f"The existing file has {file_n} data columns, but currently {self.n_channels} channels are detected.")
                    msg2.setInformativeText("Overwrite will clear the existing data. Append will continue but may misalign columns. Cancel aborts recording.")
                    ow_btn = msg2.addButton('Overwrite', QMessageBox.AcceptRole)
                    ap_btn = msg2.addButton('Append anyway', QMessageBox.AcceptRole)
                    ca_btn = msg2.addButton('Cancel', QMessageBox.RejectRole)
                    msg2.exec_()
                    clicked2 = msg2.clickedButton()
                    if clicked2 == ca_btn:
                        return
                    elif clicked2 == ow_btn:
                        mode = 'w'
                    else:
                        mode = 'a'

            f = open(path, mode=mode, newline='')
            writer = csv.writer(f)
            # remember path and whether header is already present
            self.log_path = path
            try:
                if mode == 'a':
                    self.header_written = (os.path.getsize(path) > 0)
                else:
                    # truncating the file means header must be re-written
                    self.header_written = False
            except Exception:
                self.header_written = False
            # Save handles for the logging thread to use
            self.log_file = f
            self.log_writer = writer
            self.recording = True
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            # reflect chosen directory back to internal state and field
            self.log_dir = target_dir
            if hasattr(self, 'dir_input'):
                self.dir_input.setText(self.log_dir)
        except Exception as e:
            print(f"Failed to open log file: {e}")

    def stop_recording(self):
        """Flush and close the CSV file safely."""
        if not self.recording:
            return

        try:
            if self.log_file:
                try:
                    self.log_file.flush()
                except Exception:
                    pass
                try:
                    self.log_file.close()
                except Exception:
                    pass
        finally:
            self.log_file = None
            self.log_writer = None
            self.log_path = None
            self.header_written = False
            self.recording = False
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Live UART Data Plotter - Real-time serial data visualization and logging'
    )
    parser.add_argument(
        '--port', '-p',
        default=SERIAL_PORT,
        type=str,
        help=f'Serial COM port (default: {SERIAL_PORT})'
    )
    parser.add_argument(
        '--baud', '-b',
        default=BAUD_RATE,
        type=int,
        help=f'Baud rate (default: {BAUD_RATE})'
    )
    
    args = parser.parse_args()
    
    # Override global config with command-line arguments
    SERIAL_PORT = args.port
    BAUD_RATE = args.baud
    
    app = QApplication(sys.argv)
    window = DataLoggerUI()
    window.show()
    sys.exit(app.exec_())