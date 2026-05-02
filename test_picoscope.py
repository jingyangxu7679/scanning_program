#This code is edited from PS2000 series example code from this link: https://github.com/picotech/picosdk-python-wrappers/blob/master/ps2000Examples/ps2000BlockExample.py
# Copyright (C) 2018 Pico Technology Ltd. See LICENSE file for terms.
#
# PS2000 BLOCK MODE EXAMPLE
# This example opens a 2000 driver device, sets up two channels and a trigger then collects a block of data.
# This data is then plotted as mV against time in ns.

import ctypes
import numpy as np
from picosdk.ps2000 import ps2000 as ps
import h5py
import os
from datetime import datetime, timezone
from picosdk.functions import adc2mV, assert_pico2000_ok


def _as_hdf5_dataset_array(values, name):
    """Convert incoming data to an HDF5-compatible ndarray."""
    arr = np.asarray(values)
    if arr.dtype.kind == "O":
        # Try numeric conversion first for waveform data.
        try:
            arr = np.asarray(values, dtype=np.float64)
        except (TypeError, ValueError):
            # Fall back to UTF-8 strings for non-numeric object arrays.
            str_dtype = h5py.string_dtype(encoding="utf-8")
            arr = np.asarray([str(v) for v in np.ravel(arr)], dtype=str_dtype).reshape(arr.shape)
    return arr


def _as_hdf5_attr_value(value):
    """Convert attribute values to HDF5-compatible scalar/array types."""
    if isinstance(value, (str, bytes, int, float, np.integer, np.floating, np.bool_)):
        return value

    if isinstance(value, np.ndarray):
        arr = value
    else:
        arr = np.asarray(value)

    if arr.ndim == 0:
        scalar = arr.item()
        if isinstance(scalar, (str, bytes, int, float, np.integer, np.floating, np.bool_)):
            return scalar
        return str(scalar)

    if arr.dtype.kind == "O":
        str_dtype = h5py.string_dtype(encoding="utf-8")
        return np.asarray([str(v) for v in np.ravel(arr)], dtype=str_dtype).reshape(arr.shape)

    return arr


def save_recording_hdf5(path, time, channels, channel_names=None, meta=None, compression="gzip", compression_opts=4, x_pos=None, y_pos=None):
    """Save time and channel data to an HDF5 file.

    - `channels` may be a dict of name->array or a list/2D-array.
    - `meta` is an optional dict stored as file attributes.
    - `x_pos` and `y_pos` are optional positions to be stored as attributes.
    """
    with h5py.File(path, "w") as f:
        time_arr = _as_hdf5_dataset_array(time, "time")
        f.create_dataset("time", data=time_arr, compression=compression, compression_opts=compression_opts)

        if isinstance(channels, dict):
            for name, arr in channels.items():
                ch_arr = _as_hdf5_dataset_array(arr, f"channels/{name}")
                f.create_dataset(f"channels/{name}", data=ch_arr, compression=compression, compression_opts=compression_opts)
        else:
            for i, arr in enumerate(channels):
                name = channel_names[i] if channel_names and i < len(channel_names) else f"ch{i+1}"
                ch_arr = _as_hdf5_dataset_array(arr, f"channels/{name}")
                f.create_dataset(f"channels/{name}", data=ch_arr, compression=compression, compression_opts=compression_opts)

        meta = dict(meta or {})
        # use timezone-aware UTC timestamp to avoid deprecation warnings
        meta.setdefault("saved_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        for k, v in meta.items():
            f.attrs[k] = _as_hdf5_attr_value(v)
        if x_pos is not None:
            f.attrs["x_pos"] = _as_hdf5_attr_value(x_pos)
        if y_pos is not None:
            f.attrs["y_pos"] = _as_hdf5_attr_value(y_pos)

def picoscope_block_mode_run(x_pos, y_pos):
    # Create status ready for use
    status = {}

    # Open 2000 series PicoScope
    # Returns handle to chandle for use in future API functions
    status["openUnit"] = ps.ps2000_open_unit()
    assert_pico2000_ok(status["openUnit"])

    # Create chandle for use
    chandle = ctypes.c_int16(status["openUnit"])

    # Set up channel A
    # handle = chandle
    # channel = PS2000_CHANNEL_A = 0
    # enabled = 1
    # coupling type = PS2000_DC = 1
    # range = PS2000_2V = 7
    # analogue offset = 0 V
    chARange = 2
    status["setChA"] = ps.ps2000_set_channel(chandle, 0, 1, 1, chARange)
    assert_pico2000_ok(status["setChA"])

    # Set up channel B
    # handle = chandle
    # channel = PS2000_CHANNEL_B = 1
    # enabled = 1
    # coupling type = PS2000_DC = 1
    # range = PS2000_2V = 7
    # analogue offset = 0 V
    chBRange = 2
    status["setChB"] = ps.ps2000_set_channel(chandle, 1, 1, 1, chBRange)
    assert_pico2000_ok(status["setChB"])

    # Set up single trigger
    # handle = chandle
    # source = PS2000_CHANNEL_A = 0
    # threshold = 1024 ADC counts
    # direction = PS2000_RISING = 0
    # delay = 0 s
    # auto Trigger = 1000 ms
    status["trigger"] = ps.ps2000_set_trigger(chandle, 0, 64, 0, 0, 1000)
    assert_pico2000_ok(status["trigger"])

    # Set number of pre and post trigger samples to be collected
    preTriggerSamples = 1000
    postTriggerSamples = 1000
    maxSamples = preTriggerSamples + postTriggerSamples

    # Get timebase information
    # WARNING: When using this example it may not be possible to access all Timebases as all channels are enabled by default when opening the scope.  
    # To access these Timebases, set any unused analogue channels to off.
    # handle = chandle
    # timebase = 8 = timebase
    # no_of_samples = maxSamples
    # pointer to time_interval = ctypes.byref(timeInterval)
    # pointer to time_units = ctypes.byref(timeUnits)
    # oversample = 1 = oversample
    # pointer to max_samples = ctypes.byref(maxSamplesReturn)
    timebase = 8
    timeInterval = ctypes.c_int32()
    timeUnits = ctypes.c_int32()
    oversample = ctypes.c_int16(1)
    maxSamplesReturn = ctypes.c_int32()
    status["getTimebase"] = ps.ps2000_get_timebase(chandle, timebase, maxSamples, ctypes.byref(timeInterval), ctypes.byref(timeUnits), oversample, ctypes.byref(maxSamplesReturn))
    assert_pico2000_ok(status["getTimebase"])

    # Run block capture
    # handle = chandle
    # no_of_samples = maxSamples
    # timebase = timebase
    # oversample = oversample
    # pointer to time_indisposed_ms = ctypes.byref(timeIndisposedms)
    timeIndisposedms = ctypes.c_int32()
    status["runBlock"] = ps.ps2000_run_block(chandle, maxSamples, timebase, oversample, ctypes.byref(timeIndisposedms))
    assert_pico2000_ok(status["runBlock"])

    # Check for data collection to finish using ps5000aIsReady
    ready = ctypes.c_int16(0)
    check = ctypes.c_int16(0)
    while ready.value == check.value:
        status["isReady"] = ps.ps2000_ready(chandle)
        ready = ctypes.c_int16(status["isReady"])

    # Create buffers ready for data
    bufferA = (ctypes.c_int16 * maxSamples)()
    bufferB = (ctypes.c_int16 * maxSamples)()

    # Get data from scope
    # handle = chandle
    # pointer to buffer_a = ctypes.byref(bufferA)
    # pointer to buffer_b = ctypes.byref(bufferB)
    # poiner to overflow = ctypes.byref(oversample)
    # no_of_values = cmaxSamples
    cmaxSamples = ctypes.c_int32(maxSamples)
    status["getValues"] = ps.ps2000_get_values(chandle, ctypes.byref(bufferA), ctypes.byref(bufferB), None, None, ctypes.byref(oversample), cmaxSamples)
    assert_pico2000_ok(status["getValues"])

    # find maximum ADC count value
    maxADC = ctypes.c_int16(32767)

    # convert ADC counts data to mV
    adc2mVChA =  adc2mV(bufferA, chARange, maxADC)
    adc2mVChB =  adc2mV(bufferB, chBRange, maxADC)

    # Create time data
    time = np.linspace(0, (cmaxSamples.value -1) * timeInterval.value, cmaxSamples.value)

    # Save data to HDF5 (instead of plotting)
    channels = {"A": np.asarray(adc2mVChA), "B": np.asarray(adc2mVChB)}
    meta = {
        "time_interval": int(timeInterval.value),
        "time_units": int(timeUnits.value),
        "chA_range": chARange,
        "chB_range": chBRange,
    }
    filename = f"picoscope_recording_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.h5"
    # save to Desktop/test_data
    save_dir = os.path.join(os.path.expanduser("~"), "Desktop", "test_data_04/27")
    os.makedirs(save_dir, exist_ok=True)
    filepath = os.path.join(save_dir, filename)
    save_recording_hdf5(filepath, time, channels, meta=meta, x_pos=x_pos, y_pos=y_pos)
    print(f"Saved recording to {filepath}")

    # Stop the scope
    # handle = chandle
    status["stop"] = ps.ps2000_stop(chandle)
    assert_pico2000_ok(status["stop"])

    # Close unitDisconnect the scope
    # handle = chandle
    status["close"] = ps.ps2000_close_unit(chandle)
    assert_pico2000_ok(status["close"])

    # display status returns
    print(status)