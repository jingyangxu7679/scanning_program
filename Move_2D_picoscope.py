"""
Example BSC20X_pythonnet.py
Example Date of Creation: 2024-04-19
Example Date of Last Modification on Github: 2024-04-19
Version of Python used for Testing: 3.9
==================
Example Description: This example controls the BSC200 series (Using the HDR50/M stage)
"""

#edited from this example: https://github.com/Thorlabs/Motion_Control_Examples/blob/main/Python/Kinesis/Benchtop/BSC20X/BSC20X_pythonnet.py
import os
import time
import sys
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
initial_pos_X=0
initial_pos_Y=0
#initial_pos_Z=1#correspond to 0.1 mm 
initial_z_focus=3852

def shift_zfocus_stage(x_pos, y_pos, initial_pos_X, initial_pos_Y, initial_pos_Z):
    #this function shifts the z axis of 3-axis motorized stage based on pre computed spatial variation of necessary z-focus
    x_pos_float = float(str(x_pos))
    y_pos_float = float(str(y_pos))
    z_start_float = float(str(initial_pos_Z))
    x_change = (x_pos_float / 1.5) * 0.04
    y_change = ((y_pos_float) / 1.5) * 0.03
    new_z_pos = z_start_float + x_change - y_change
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

        channel_config.DeviceSettingsName = 'HDR50/M'

        channel_config.UpdateCurrentConfiguration()

        channel.SetSettings(chan_settings, True, False)

        # Do the same for channel 2
        channel_config_2 = channel_2.LoadMotorConfiguration(channel_2.DeviceID)
        chan_settings_2 = channel_2.MotorDeviceSettings
        channel_2.GetSettings(chan_settings_2)
        channel_config_2.DeviceSettingsName = 'HDR50/M'
        channel_config_2.UpdateCurrentConfiguration()
        channel_2.SetSettings(chan_settings_2, True, False)

        # Do the same for channel 3
        channel_config_3 = channel_3.LoadMotorConfiguration(channel_3.DeviceID)
        chan_settings_3 = channel_3.MotorDeviceSettings
        channel_3.GetSettings(chan_settings_3)
        channel_config_3.DeviceSettingsName = 'HDR50/M'
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
        csv_filename = f"motor_pos_time_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path = os.path.join(output_dir, csv_filename)

        tz_minus_7 = timezone(timedelta(hours=-7))

        csv_file = open(csv_path, "w", newline="", encoding="utf-8")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["Time (UTC -07:00 yyyy-MM-dd HH:mm:ss)", "x_pos", " y_pos"])
        print(f"Saving motor position timestamps to: {csv_path}")
        step_size = 0.1  #should correspond to *0.1 mm for the stage
        y_step_size = 0.1
        #time.sleep(1)
        #z_focus_counter=0
        try:
            for M in range(11):
                print("Moving channel 2...")
                channel_2.MoveTo(Decimal(y_step_size*M), 60000)
                print(f"Channel 2 position changed. Position = {channel_2.DevicePosition}")

                for N in range (41):
                    channel.MoveTo(Decimal(step_size*N), 60000)
                    print(f"Channel 1 position changed. Position = {channel.DevicePosition}")
                    #time.sleep(1)
                    x_pos = channel.DevicePosition
                    y_pos = channel_2.DevicePosition
                    print(f"Current x position: {x_pos}, Current y position: {y_pos}")
                    #if N%5==0:
                    print("Adjust z focus")
                    time.sleep(1)
                    #Control_picometer8742.adjust_focus(x_current=x_pos, y_current=y_pos, initial_pos_X=initial_pos_X, initial_pos_Y=initial_pos_Y, initial_z_focus=initial_z_focus)  # adjust z focus to initial_z_focus (900 steps = 90 um)
                    #if N%5==0: # adjust z focus every 15 steps in x direction (every 1.5 mm)
                        #z_focus_pos=shift_zfocus_stage(x_pos, y_pos, initial_pos_X, initial_pos_Y, initial_pos_Z) 
                    
                        #channel_3.MoveTo(z_focus_pos, 60000)
                        #z_actual = channel_3.DevicePosition
                        #z_error = float(str(z_actual)) - float(str(z_focus_pos))
                        #print(f"Z command: {z_focus_pos}, Z actual: {z_actual}, Z error: {z_error}")
                    timestamp_str = datetime.now(tz_minus_7).strftime("%Y-%m-%d %H:%M:%S")
                    csv_writer.writerow([timestamp_str, str(x_pos), str(y_pos)])#can also store z pos later
                    csv_file.flush()
                    time.sleep(1)

                    N=N+1
                #test_picoscope.picoscope_block_mode_run()  # run the picoscope example to show that the two can be used together without issue

                time.sleep(1)
                N=N+1
        finally:
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
