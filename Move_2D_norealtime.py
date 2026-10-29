"""
Example BSC20X_pythonnet.py
Example Date of Creation: 2024-04-19
Example Date of Last Modification on Github: 2024-04-19
Version of Python used for Testing: 3.9
==================
Example Description: This example controls the BSC200 series (Using the HDR50/M stage)
Scan move completions are timestamped in the console and a .txt log in Desktop/scan_timebudget;
the existing per-point CSV output is retained.
"""

#edited from this example: https://github.com/Thorlabs/Motion_Control_Examples/blob/main/Python/Kinesis/Benchtop/BSC20X/BSC20X_pythonnet.py
import os
import time
import csv
import clr
from datetime import datetime, timezone, timedelta

clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\Thorlabs.MotionControl.DeviceManagerCLI.dll")
clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\Thorlabs.MotionControl.GenericMotorCLI.dll")
clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\ThorLabs.MotionControl.Benchtop.StepperMotorCLI.dll")
import Control_picometer8742
from Thorlabs.MotionControl.DeviceManagerCLI import *
from Thorlabs.MotionControl.GenericMotorCLI import *
from Thorlabs.MotionControl.Benchtop.StepperMotorCLI import *
from System import Decimal  # necessary for real world units
import test_picoscope


initial_pos=0
initial_pos_X=2.2
initial_pos_Y=2.2
#initial_pos_Z=1#correspond to 0.1 mm 
initial_z_focus=3852

# NOTE: unlike Move_2D_picoscope.py / Move_2D_norealtime's earlier version, this file
# calls test_picoscope.picoscope_block_mode_run() directly in-process (no subprocess),
# per explicit request. This re-introduces the risk described in test_picoscope.py:
# mixing pythonnet's hosted .NET CLR (used here for Thorlabs/Kinesis) with the
# PicoScope SDK's native ctypes calls in the same process previously caused a fatal
# "PyEval_RestoreThread ... GIL released" crash. If that crash recurs, revert to the
# subprocess.run([...]) approach used in Move_2D_picoscope.py.

CSV_DIRNAME = "CSV_single"
GRAPH_DIRNAME = "GRAPH_single"

# ThorCam focus map 2026-10-28 15:01 (resolution_cv.py): plane (tilt) fit, 26 points, rms 0.00191
# z_focus(x, y) = Z0 + DZ_DX * (x - XC) + DZ_DY * (y - YC)
# The map was measured through basic_motor_control.py (Motor_GUI / resolution_cv.py), which loads the
# "HDR50/M" stage settings (75093 controller steps per unit). This script loads "HS NanoMax 300 ... (DRV208)"
# (819200 steps per unit, same as the Kinesis GUI), so the same physical position reads differently, e.g. raw Z
# counter 168535 = 2.24434 there but 0.205731 here. Positions (Z0, XC, YC, x, y) are converted with
# FOCUS_MAP_UNIT_SCALE; the slopes are dimensionless (x, y and z scale equally) and need no conversion.
# Paste future resolution_cv.py fit numbers below unchanged (in HDR50/M units).
FOCUS_MAP_Z0 = 2.2864687
FOCUS_MAP_DZ_DX = 0.04563134
FOCUS_MAP_DZ_DY = 0.024761352
FOCUS_MAP_XC = 1.102565
FOCUS_MAP_YC = 0.269231
MAP_STEPS_PER_UNIT = 75093.0      # HDR50/M settings used by basic_motor_control.py
STAGE_STEPS_PER_UNIT = 819200.0   # HS NanoMax 300 (DRV208) settings used in main() below
FOCUS_MAP_UNIT_SCALE = MAP_STEPS_PER_UNIT / STAGE_STEPS_PER_UNIT  # map units -> this script's units
# False: move z to the absolute best-focus z measured by the focus map.
# True: use only the map's tilt, anchored to the z the scan starts at: z0 + f(x, y) - f(x0, y0).
FOCUS_MAP_ANCHOR_TO_START = False
# Focus-map targets are not restricted by their distance from the starting Z.


def log_position_change(log_file, axis, target, channels, tz):
    """Record the position readbacks immediately after a blocking move completes."""
    timestamp = datetime.now(tz).isoformat(timespec="milliseconds")
    positions = ", ".join(f"{name}={channel.DevicePosition}" for name, channel in channels)
    line = f"[{timestamp}] {axis} move completed: target={target}; {positions}"
    print(line, flush=True)
    log_file.write(line + "\n")
    log_file.flush()


def focus_map_z(x, y):
    # x, y and the returned z are in this script's (NanoMax) units
    s = FOCUS_MAP_UNIT_SCALE
    return (FOCUS_MAP_Z0 * s
            + FOCUS_MAP_DZ_DX * (x - FOCUS_MAP_XC * s)
            + FOCUS_MAP_DZ_DY * (y - FOCUS_MAP_YC * s))


def shift_zfocus_stage(x_pos, y_pos, initial_pos_X, initial_pos_Y, initial_pos_Z):
    # this function shifts the z axis of 3-axis motorized stage based on the ThorCam focus map plane fit
    x_pos_float = float(str(x_pos))
    y_pos_float = float(str(y_pos))
    z_start_float = float(str(initial_pos_Z))
    if FOCUS_MAP_ANCHOR_TO_START:
        x_start_float = float(str(initial_pos_X))
        y_start_float = float(str(initial_pos_Y))
        new_z_float = z_start_float + focus_map_z(x_pos_float, y_pos_float) - focus_map_z(x_start_float, y_start_float)
    else:
        new_z_float = focus_map_z(x_pos_float, y_pos_float)
    new_z_pos = Decimal(round(new_z_float, 6))
    print(f"Shifting z focus stage to new position: {new_z_pos}")
    return new_z_pos


def shift_zfocus_stage_manual(x_pos, y_pos, initial_pos_X, initial_pos_Y, initial_pos_Z):
    # previous hand-tuned piecewise z correction (kept for reference; not used)
    x_pos_float = float(str(x_pos))
    y_pos_float = float(str(y_pos))
    z_start_float = float(str(initial_pos_Z))
    #x_change = (x_pos_float / 1.5) * 0.04
    if x_pos_float < 2.55:
        x_change = ((x_pos_float - 2.20) / 0.05) * 0.001
    else:
        x_change = ((2.55 - 2.20) / 0.05) * 0.001 + ((x_pos_float - 2.55) / 0.05) * 0.0015
    if y_pos_float < 2.35:
        y_change = 0.0
    elif y_pos_float < 2.45:
        y_change = 0.001
    elif y_pos_float < 2.55:
        y_change = 0.002
    elif y_pos_float < 2.65:
        y_change = 0.003
    elif y_pos_float < 2.70:
        y_change = 0.004
    else:
        y_change = 0.005
    #if x_pos_float>0.5:
        #x_change = (x_pos_float / 0.1) * 0.003
    #else:
    #    x_change=0
    #new_z_pos = z_start_float + x_change - y_change
    new_z_pos = z_start_float + x_change + y_change

    new_z_pos = Decimal(new_z_pos)
    print(f"Shifting z focus stage to new position: {new_z_pos}")
    return new_z_pos

def main():

    # Comment out this line for the real device
    #SimulationManager.Instance.InitializeSimulations()
    try:
        DeviceManagerCLI.BuildDeviceList()

        # create new device
        serial_no = "70536944"  # Replace this line with your device's serial number

        # Connect, begin polling, and enable
        device = BenchtopStepperMotor.CreateBenchtopStepperMotor(serial_no)
        device.Connect(serial_no)
        time.sleep(0.25)  # wait statements are important to allow settings to be sent to the device

        # For benchtop devices, get the channel
        channel = device.GetChannel(1)
        channel_2 = device.GetChannel(2)
        channel_3= device.GetChannel(3)

        # Ensure that the device settings have been initialized
        if not channel.IsSettingsInitialized():
            channel.WaitForSettingsInitialized(10000)  # 10 second timeout
            assert channel.IsSettingsInitialized() is True
        if not channel_2.IsSettingsInitialized():
            channel_2.WaitForSettingsInitialized(10000)  # 10 second timeout
            assert channel_2.IsSettingsInitialized() is True
        if not channel_3.IsSettingsInitialized():
            channel_3.WaitForSettingsInitialized(10000)  # 10 second timeout
            assert channel_3.IsSettingsInitialized() is True
        # Start polling and enable
        channel.StartPolling(250)  # 250ms polling rate
        time.sleep(0.25)
        channel.EnableDevice()
        time.sleep(1.0)  # Wait for device to enable
        channel_2.StartPolling(250)  # 250ms polling rate
        time.sleep(0.25)    
        channel_2.EnableDevice()
        time.sleep(1.0)  # Wait for device to enable
        channel_3.StartPolling(250)  # 250ms polling rate
        time.sleep(0.25)
        channel_3.EnableDevice()
        time.sleep(1.0)  # Wait for device to enable
        
        # Get Device Information and display description
        device_info = channel.GetDeviceInfo()
        print(device_info.Description)
        device_info_2 = channel_2.GetDeviceInfo()
        print(device_info_2.Description)
        device_info_3 = channel_3.GetDeviceInfo()
        print(device_info_3.Description)

        # Load any configuration settings needed by the controller/stage
        channel_config = channel.LoadMotorConfiguration(channel.DeviceID)
        chan_settings = channel.MotorDeviceSettings

        channel.GetSettings(chan_settings)

        channel_config.DeviceSettingsName = 'HS NanoMax 300 X Axis (DRV208)'

        channel_config.UpdateCurrentConfiguration()

        channel.SetSettings(chan_settings, True, False)

        # Do the same for channel 2
        channel_config_2 = channel_2.LoadMotorConfiguration(channel_2.DeviceID)
        chan_settings_2 = channel_2.MotorDeviceSettings
        channel_2.GetSettings(chan_settings_2)
        channel_config_2.DeviceSettingsName = 'HS NanoMax 300 Y Axis (DRV208)'
        channel_config_2.UpdateCurrentConfiguration()
        channel_2.SetSettings(chan_settings_2, True, False)

        # Do the same for channel 3
        channel_config_3 = channel_3.LoadMotorConfiguration(channel_3.DeviceID)
        chan_settings_3 = channel_3.MotorDeviceSettings
        channel_3.GetSettings(chan_settings_3)
        channel_config_3.DeviceSettingsName = 'HS NanoMax 300 Z Axis (DRV208)'
        channel_config_3.UpdateCurrentConfiguration()
        channel_3.SetSettings(chan_settings_3, True, False)

        # Home or Zero the device (if a motor/piezo)
        print("Homing Motor for channel 1")
        #channel.Home(60000)
        print("Homing Completed")

        print("Homing Motor for channel 2")
        #channel_2.Home(60000)
        print("Homing Completed")

        # Use the live z position as the baseline so focus offsets are referenced to real device coordinates.
        initial_pos_Z = channel_3.DevicePosition
        print(f"Initial z baseline position: {initial_pos_Z}")

        output_dir = os.path.join(os.path.expanduser("~"), "Desktop", "motor_pos_time")
        os.makedirs(output_dir, exist_ok=True)
        run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_filename = f"motor_pos_time_{run_timestamp}.csv"
        csv_path = os.path.join(output_dir, csv_filename)
        log_dir = os.path.join(os.path.expanduser("~"), "Desktop", "scan_timebudget")
        os.makedirs(log_dir, exist_ok=True)
        txt_path = os.path.join(log_dir, f"motor_pos_time_{run_timestamp}.txt")

        tz_minus_7 = timezone(timedelta(hours=-7))

        csv_file = open(csv_path, "w", newline="", encoding="utf-8")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["Time (UTC -07:00 yyyy-MM-dd HH:mm:ss)", "x_pos", " y_pos"])
        print(f"Saving motor position timestamps to: {csv_path}")
        step_size = 0.01  #should correspond to *0.1 mm for the stage
        y_step_size = 0.01
        x_start_pos = float(str(channel.DevicePosition))  # scan starts at this x position instead of 0.0
        y_start_pos = float(str(channel_2.DevicePosition))  # scan starts at this y position instead of 0.0
        initial_pos_X = x_start_pos
        initial_pos_Y = y_start_pos
        print (f"Initial x position: {initial_pos_X}, Initial y position: {initial_pos_Y}, Initial z position: {initial_pos_Z}")
        initial_pos_Z = channel_3.DevicePosition
        #time.sleep(1)
        #z_focus_counter=0
        txt_file = None
        try:
            txt_file = open(txt_path, "w", encoding="utf-8")
            txt_file.write("Move completion timestamps (UTC -07:00); positions in configured stage units.\n")
            txt_file.flush()
            print(f"Saving move timestamps to: {txt_path}")
            scan_channels = (("X", channel), ("Y", channel_2), ("Z", channel_3))
            for M in range(41):#41
                print("Moving channel 2...")
                y_target = Decimal(y_start_pos + y_step_size*M)
                channel_2.MoveTo(y_target, 60000)
                log_position_change(txt_file, "Y", y_target, scan_channels, tz_minus_7)
                #time.sleep(1)
                print(f"Channel 2 position changed. Position = {channel_2.DevicePosition}")

                # Zigzag (boustrophedon) scan: alternate x direction every other row so
                # the stage moves directly from the end of one row to the start of the
                # next, instead of always jumping all the way back to x_start_pos - this
                # avoids the large backlash-prone reset jump at the start of every row.
                x_indices = range(121) if M % 2 == 0 else range(120, -1, -1)
                for N in x_indices:#41
                    x_target = Decimal(x_start_pos + step_size*N)
                    channel.MoveTo(x_target, 60000)
                    log_position_change(txt_file, "X", x_target, scan_channels, tz_minus_7)
                    print(f"Channel 1 position changed. Position = {channel.DevicePosition}")
                    #time.sleep(1)
                    x_pos = channel.DevicePosition
                    y_pos = channel_2.DevicePosition
                    print(f"Current x position: {x_pos}, Current y position: {y_pos}")
                    #if N%5==0:
                    print("Adjust z focus")
                    #time.sleep(1)
                    #Control_picometer8742.adjust_focus(x_current=x_pos, y_current=y_pos, initial_pos_X=initial_pos_X, initial_pos_Y=initial_pos_Y, initial_z_focus=initial_z_focus)  # adjust z focus to initial_z_focus (900 steps = 90 um)
                    if N%5==0: # adjust z focus every 15 steps in x direction (every 1.5 mm)
                        z_focus_pos=shift_zfocus_stage(x_pos, y_pos, initial_pos_X, initial_pos_Y, initial_pos_Z) 
                    
                        channel_3.MoveTo(z_focus_pos, 60000)
                        log_position_change(txt_file, "Z", z_focus_pos, scan_channels, tz_minus_7)
                        z_actual = channel_3.DevicePosition
                        z_error = float(str(z_actual)) - float(str(z_focus_pos))
                        print(f"Z command: {z_focus_pos}, Z actual: {z_actual}, Z error: {z_error}")
                    #time.sleep(1)
                    # Convert .NET Decimal device positions to plain Python floats up front -
                    # picoscope_block_mode_run's filename/attribute formatting (e.g. f"{value:.3f}")
                    # raises a TypeError on a raw System.Decimal.
                    x_pos_f = float(str(x_pos))
                    y_pos_f = float(str(y_pos))

                    # Run the PicoScope capture directly in this process (no subprocess).
                    #test_picoscope.picoscope_block_mode_run(x_pos=x_pos_f, y_pos=y_pos_f)

                    timestamp_str = datetime.now(tz_minus_7).strftime("%Y-%m-%d %H:%M:%S")
                    csv_writer.writerow([timestamp_str, str(x_pos), str(y_pos)])#can also store z pos later
                    csv_file.flush()
                    #time.sleep(1)

                    N=N+1
                

                #time.sleep(1)
                N=N+1
        finally:
            if txt_file is not None:
                txt_file.close()
            csv_file.close()

        #Home after moving 
        #channel.Home(60000)
        #channel_2.Home(60000)
        #channel_3.Home(60000)
        # Stop Polling and Disconnect
        channel.StopPolling()
        channel_2.StopPolling()
        channel_3.StopPolling()

        device.Disconnect()

    except Exception as e:
        # this can be bad practice: It sometimes obscures the error source
        print(e)

    # Comment this line for the real device
    #SimulationManager.Instance.UninitializeSimulations()

if __name__ == "__main__":
    main()
