# UART Logger

UART Logger is a Python/Qt desktop tool for streaming serial data, plotting live values, and recording comma-separated measurements to CSV files. It supports multi-channel input, custom channel labels, and CSV-based label import. A companion viewer script lets you replay and inspect recorded CSV files without needing a connected device.

**Quick Start**
- Install Python 3.8+.
- Install dependencies:

```bash
pip install pyqt5 pyqtgraph pyserial numpy
```

- Run the logger (example):

```bash
python uart_logger.py --port COM5 --baud 921600
```

- View a recorded file:

```bash
python data_viewer.py                      # opens a file picker
python data_viewer.py data/ekg_demo.csv   # opens a specific file
```

**Usage & CLI — Logger**
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
- By default logs are saved to the `data` folder next to the script.

**Expected Serial Input**
- Each incoming serial line should contain one or more numeric values separated by commas.
- Examples:
  - Single channel: `12.34`
  - Two channels: `12.34,56.78`
  - Three channels: `1.2,3.4,5.6`
- The program will ignore lines that cannot be parsed as numbers.
- If the line contains fewer values than the number of detected channels, missing values are treated as empty/missing for that sample.

**Output File Format**
- Recorded files are CSVs with a timestamp column followed by one column per detected channel.
- Example header:

```csv
timestamp,Temperature,Pressure
2026-06-28 12:00:00.123,21.5,101.3
2026-06-28 12:00:01.456,21.7,101.2
```

- If you rename channels in the GUI, those names are used in the CSV header for future rows.
- Existing CSV files are appended to by default when you choose **Append**.

**Importing Labels from a CSV**
- You can use the **Edit Channel Labels** dialog and click **Import from CSV**.
- The importer reads the first row of the selected CSV and uses it as the channel label list.
- If the first row starts with `timestamp`, that column is skipped.
- If the imported CSV has more labels than detected channels, only the first matching labels are used.

**Data Viewer**

`data_viewer.py` is a standalone companion for inspecting recorded CSV files. It uses the same PyQt5/pyqtgraph stack as the logger and opens any CSV written by the logger (or any CSV with the same `timestamp,chan1,...` format).

- **Open CSV…** — file picker defaults to the `data/` folder next to the script.
- **X Axis** — switch between *Sample Index* and *Time (s)* (seconds elapsed since the first timestamp).
- **Y Min / Y Max / Autoscale** — same Y-axis controls as the logger.
- **Channel checkboxes** — toggle individual channels on/off; each checkbox is color-coded to its plot line.
- Mouse pan and zoom are available via pyqtgraph's built-in interactions (right-click drag to zoom, scroll wheel to zoom an axis, middle-click to pan).

**Notes & Troubleshooting**
- If the serial port fails to open the app will print an error and exit; verify the port name and permissions.
- If multiple channels appear, the UI creates one plot per channel and a legend.
- The application avoids modifying existing recorded CSV files except when you explicitly choose "Overwrite".

**High Sample Rate / Bursty Display**

At high sample rates (e.g. 1 kHz) the live plot and recorded timestamps may appear bursty — data arrives in discrete clumps rather than continuously. There are two causes:

1. **USB-serial adapter latency timer.** USB-to-serial adapters (CP210x, FTDI, CH340, etc.) batch incoming bytes and deliver them to the OS on a periodic timer. The default is often **16 ms**, so at 1 kHz you receive 16 samples all at once rather than one per millisecond. Reducing this timer to **1 ms** (the minimum) dramatically smooths both the live display and the recorded timestamps.

   *Windows:* Device Manager → Ports (COM & LPT) → right-click your adapter → Properties → Port Settings → Advanced → **Latency Timer (msec)** → set to `1`.

2. **Single-line reads.** The logger previously called `readline()` for each sample, which reads one byte at a time internally and amplifies the bursty delivery. The current version reads all bytes available in the OS buffer in a single call (`read(n)`), so each burst is drained immediately.

   The latency timer change (step 1) is the most impactful fix for timestamp accuracy. The code change ensures the buffer is processed as fast as possible once data does arrive.