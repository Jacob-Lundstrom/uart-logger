**Quick Start**
- Install Python 3.8+.
- Install dependencies:

```bash
pip install pyqt5 pyqtgraph pyserial
```

- Run the GUI (example):

```bash
python uart_logger.py --port COM5 --baud 921600
```

**Usage & CLI**
- `--port`, `-p`: serial port (e.g., COM3 or /dev/ttyUSB0).
- `--baud`, `-b`: baud rate (default 921600).

**GUI Controls**
- **X-Axis Sample Width:** Number of recent samples shown.
- **Y Min / Y Max / Autoscale:** Toggle autoscale or set fixed Y range.
- **Output Directory:** Where CSV recordings are saved (editable).
- **Filename:** Name for recorded CSV.
- **Start Recording / Stop Recording:** Begin/stop logging to CSV.
- **Edit Channel Labels:** Open a dialog to name channels; you can import labels from a CSV header.
- **Reset Data/Channels:** Clears in-memory data and detected channels only (recorded CSVs are not modified).

**Data Format & Logging**
- The script accepts comma-separated numeric values per serial line (any number of channels).
- CSV rows are written as: `timestamp, chan1, chan2, ...`.
- When creating a new file the header is written automatically. If the chosen file already exists you will be prompted to Overwrite (truncate), Append, or Cancel.
- When appending, the script reads the existing file's header (if present) and compares column count to the detected channels. If they differ you will be prompted to Overwrite, Append anyway, or Cancel.

**Default Data Directory**
- By default logs are saved to the `data` folder next to the script: [data](data)

**Notes & Troubleshooting**
- If the serial port fails to open the app will print an error and exit; verify the port name and permissions.
- If multiple channels appear, the UI creates one plot per channel and a legend.
- The application avoids modifying existing recorded CSV files except when you explicitly choose "Overwrite".

**Contributing**
- Feel free to open issues or PRs to add features (label persistence, column mapping, etc.).

**Files**
- Main script: [uart_logger.py](uart_logger.py#L1)
