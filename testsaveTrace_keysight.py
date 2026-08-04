"""
keysight_ktxsan Python API - Acquire Trace and Save Locally

Connects to the instrument, acquires a fresh trace (X/Y data), and saves it
locally as a CSV file using numpy.

Requires Python 3.10 (per project convention) and keysight_ktxsan Python module installed.
"""

import argparse
import datetime
from pathlib import Path

import keysight_ktxsan
import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(description="Acquire an EXA N9010A trace and save it locally.")
    parser.add_argument("--x-pos", type=float, default=None, help="Stage X position (recorded in the output filename).")
    parser.add_argument("--y-pos", type=float, default=None, help="Stage Y position (recorded in the output filename).")
    return parser.parse_args()


def scpi_query(driver, command):
    """Send a SCPI query and return the raw string response.

    Bypasses the keysight_ktxsan driver's built-in fetch_x/fetch_y/read_y
    methods, which have a known response-parsing bug (raises
    "IndexError: invalid string position") against this instrument.
    """
    driver.system.write_string(command)
    return driver.system.read_string().strip()


def main():
    args = parse_args()

    resource_name = "TCPIP0::169.254.253.122::5025::SOCKET"
    idQuery = True
    reset   = True
    options = "QueryInstrStatus=False, Simulate=False, Trace=False"

    # Frequency range to record. Set both to None to leave the instrument's
    # current start/stop frequency unchanged instead of overriding it.
    start_freq_hz = 65000   # e.g. 1e6 for 1 MHz
    stop_freq_hz = 73000    # e.g. 100e6 for 100 MHz
    # Number of sweep points to record. Set to None to leave unchanged.
    num_sweep_points = 99900  # e.g. 1001
    # Resolution bandwidth (RBW) in Hz. Set to None to leave RBW auto-coupled
    # (instrument picks RBW automatically based on span) instead of overriding it.
    resolution_bandwidth_hz = 1  # e.g. 10 for 10 Hz RBW

    output_dir = Path.home() / "Desktop" / "Keysight_EXA_N9010A"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.x_pos is not None and args.y_pos is not None:
        filename = "ONtrace_data_x{:.4f}_y{:.4f}_{}.csv".format(args.x_pos, args.y_pos, timestamp)
    else:
        filename = "ONtrace_data_{}.csv".format(timestamp)
    output_file = output_dir / "0731_test1_UCLA" / filename
    output_file.parent.mkdir(parents=True, exist_ok=True)
    acquisition_timeout_s = 10.0

    driver = None
    try:
        print("\n  keysight_ktxsan Save Trace Example\n")

        driver = keysight_ktxsan.KtXSAn(resource_name, idQuery, reset, options)
        print("Driver Initialized")

        print('  identifier: ', driver.identity.identifier)
        print('  model:      ', driver.identity.instrument_model)
        print('  resource:   ', driver.driver_operation.io_resource_descriptor)

        # Get the first trace in the traces collection (e.g. "Trace1")
        trace_name, trace = next(iter(driver.traces.items()))
        print("\n  Using trace:", trace_name)

        # Configure the frequency range/points to record, if specified.
        if start_freq_hz is not None and stop_freq_hz is not None:
            driver.frequency.configure_start_stop(start_freq_hz, stop_freq_hz)
            print("  Frequency range set to {:,.1f} Hz - {:,.1f} Hz".format(start_freq_hz, stop_freq_hz))
        if num_sweep_points is not None:
            driver.system.write_string(":SWEEP:POINTS {}".format(num_sweep_points))
            print("  Sweep points set to", num_sweep_points)
        if resolution_bandwidth_hz is not None:
            # Disable RBW auto-coupling first, otherwise the instrument will
            # override the explicit value based on the current span.
            driver.system.write_string(":BANDWIDTH:RESOLUTION:AUTO OFF")
            driver.system.write_string(":BANDWIDTH:RESOLUTION {}".format(resolution_bandwidth_hz))
            print("  Resolution bandwidth set to {:,.1f} Hz".format(resolution_bandwidth_hz))

        # Use single-sweep mode so we control exactly when a sweep starts and
        # can reliably wait for it to finish before fetching data.
        driver.acquisition.continuous_sweep_mode_enabled = False

        # Start a sweep, then block until the instrument reports the operation
        # is complete (avoids the buggy acquisition_status() enum parsing and
        # the race condition of fetching before the sweep finishes).
        print("  Initiating sweep...")
        driver.traces.initiate()
        driver.system.wait_for_operation_complete(
            datetime.timedelta(seconds=acquisition_timeout_s)
        )
        print("  Sweep complete")

        # Fetch the trace data via raw SCPI instead of the driver's
        # fetch_y()/fetch_x()/read_y(), which fail with
        # "IndexError: invalid string position" on this instrument.
        driver.system.write_string(":FORMAT:DATA ASCII")
        y_raw = scpi_query(driver, ":TRACE:DATA? {}".format(trace_name))
        y_data = np.array([float(v) for v in y_raw.split(",") if v], dtype=np.float64)

        start_freq = float(scpi_query(driver, ":FREQUENCY:START?"))
        stop_freq = float(scpi_query(driver, ":FREQUENCY:STOP?"))
        num_points = int(float(scpi_query(driver, ":SWEEP:POINTS?")))
        x_data = np.linspace(start_freq, stop_freq, num_points)

        print("  Read {} Y points, {} X points".format(len(y_data), len(x_data)))

        if len(y_data) == 0 or len(x_data) == 0:
            raise RuntimeError("Trace returned 0 points; check instrument mode/state")

        # Save locally as CSV
        np.savetxt(
            output_file,
            np.column_stack((x_data, y_data)),
            delimiter=",",
            header="frequency_hz,amplitude",
            comments="",
        )
        print("  Saved trace data to:", output_file)

        # Check instrument for errors
        print()
        while True:
            outVal = driver.utility.error_query()
            print("  error_query: code:", outVal[0], " message:", outVal[1])
            if outVal[0] == 0:  # 0 = No error, error queue empty
                break

    except Exception as e:
        print("\n  Exception:", e.__class__.__name__, e.args)

    finally:
        if driver is not None:
            driver.close()
        # Only pause for a keypress when run interactively (no --x-pos/--y-pos),
        # otherwise this would hang forever when invoked as a subprocess during
        # an automated scan (e.g. from Move_2D_1064.py).
        if args.x_pos is None and args.y_pos is None:
            input("\nDone - Press Enter to Exit")


if __name__ == "__main__":
    main()

