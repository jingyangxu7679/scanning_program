"""
Example BSC20X_pythonnet.py
Example Date of Creation: 2024-04-19
Example Date of Last Modification on Github: 2024-04-19
Version of Python used for Testing: 3.9
==================
Example Description: This example controls the BSC200 series (Using the HDR50/M stage)
"""
import os
import time
import sys
import clr

clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\Thorlabs.MotionControl.DeviceManagerCLI.dll")
clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\Thorlabs.MotionControl.GenericMotorCLI.dll")
clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\ThorLabs.MotionControl.Benchtop.StepperMotorCLI.dll")
from Thorlabs.MotionControl.DeviceManagerCLI import *
from Thorlabs.MotionControl.GenericMotorCLI import *
from Thorlabs.MotionControl.Benchtop.StepperMotorCLI import *
from System import Decimal  # necessary for real world units

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

        # Ensure that the device settings have been initialized
        if not channel.IsSettingsInitialized():
            channel.WaitForSettingsInitialized(10000)  # 10 second timeout
            assert channel.IsSettingsInitialized() is True
        if not channel_2.IsSettingsInitialized():
            channel_2.WaitForSettingsInitialized(10000)  # 10 second timeout
            assert channel_2.IsSettingsInitialized() is True
        # Start polling and enable
        channel.StartPolling(250)  # 250ms polling rate
        time.sleep(0.25)
        channel.EnableDevice()
        time.sleep(0.25)  # Wait for device to enable
        channel_2.StartPolling(250)  # 250ms polling rate
        time.sleep(0.25)    
        channel_2.EnableDevice()
        time.sleep(0.25)  # Wait for device to enable
        
        # Get Device Information and display description
        device_info = channel.GetDeviceInfo()
        print(device_info.Description)
        device_info_2 = channel_2.GetDeviceInfo()
        print(device_info_2.Description)

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


        # Home or Zero the device (if a motor/piezo)
        print("Homing Motor for channel 1")
        channel.Home(60000)
        print("Homing Completed")

        print("Homing Motor for channel 2")
        channel_2.Home(60000)
        print("Homing Completed")

        step_size = 5
        time.sleep(2)
        for N in range(5):
            print("Moving...")
            channel.MoveTo(Decimal(step_size*N), 60000)
            channel_2.MoveTo(Decimal(step_size*N), 60000)
            print(f"Position = {channel.DevicePosition}")
            print(f"Position = {channel_2.DevicePosition}")
            time.sleep(2)
            N=N+1
        #Home after moving 
        channel.Home(60000)
        channel_2.Home(60000)
        # Stop Polling and Disconnect
        channel.StopPolling()
        channel_2.StopPolling()
        device.Disconnect()

    except Exception as e:
        # this can be bad practice: It sometimes obscures the error source
        print(e)

    # Comment this line for the real device
    #SimulationManager.Instance.UninitializeSimulations()

if __name__ == "__main__":
    main()
