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
                             QPushButton, QFileDialog, QSizePolicy)
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
        # deque is highly optimized for appending to one end and popping from the other
        self.data_buffer = deque(maxlen=MAX_HISTORY)
        self.window_size = 100 # Default X-axis sample width
        # Logging state
        self.log_dir = os.getcwd()
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
        
        # Create the line plot
        self.plot_curve = self.graph.plot(pen=pg.mkPen(color='b', width=2))

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
                        # Parse the data (Assuming one numeric value per line)
                        # If you have multiple values, split them here
                        val = float(decoded_line)

                        # Append to the plot buffer
                        self.data_buffer.append(val)

                        # Log to CSV only when recording is active
                        if self.recording and self.log_writer and self.log_file:
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                            try:
                                self.log_writer.writerow([timestamp, val])
                                self.log_file.flush()
                            except Exception:
                                # If writing fails for any reason, stop recording to be safe
                                self.stop_recording()

                except (UnicodeDecodeError, ValueError):
                    # Ignores corrupted bytes or non-numeric lines 
                    pass

    def update_plot(self):
        """Pulls the latest data slice and updates the graph."""
        if not self.data_buffer:
            return

        # Convert deque to a list so we can slice it
        current_data = list(self.data_buffer)
        
        # Apply the moving window requested by the text field
        if len(current_data) > self.window_size:
            current_data = current_data[-self.window_size:]
            
        # Update the pyqtgraph curve
        self.plot_curve.setData(current_data)

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
            f = open(path, mode='a', newline='')
            writer = csv.writer(f)
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