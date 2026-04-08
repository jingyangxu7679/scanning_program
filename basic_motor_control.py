import os
import time
import clr

clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\Thorlabs.MotionControl.DeviceManagerCLI.dll")
clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\Thorlabs.MotionControl.GenericMotorCLI.dll")
clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\ThorLabs.MotionControl.Benchtop.StepperMotorCLI.dll")
from Thorlabs.MotionControl.DeviceManagerCLI import *
from Thorlabs.MotionControl.GenericMotorCLI import *
from Thorlabs.MotionControl.Benchtop.StepperMotorCLI import *
from System import Decimal  # necessary for real world units

SERIAL_NO = os.getenv("THORLABS_BSC_SERIAL", "70536944")
DEFAULT_CHANNELS = (1, 2)


# IP address is not used for Kinesis USB control; kept for compatibility with existing callers.
def connect_and_move(_ip_addr, channel_num, pos_num):
    device = None
    channel = None
    try:
        DeviceManagerCLI.BuildDeviceList()

        device = BenchtopStepperMotor.CreateBenchtopStepperMotor(SERIAL_NO)
        device.Connect(SERIAL_NO)
        time.sleep(0.25)

        channel = device.GetChannel(channel_num)

        if not channel.IsSettingsInitialized():
            channel.WaitForSettingsInitialized(10000)
            assert channel.IsSettingsInitialized() is True

        channel.StartPolling(250)
        time.sleep(0.25)
        channel.EnableDevice()
        time.sleep(0.25)

        device_info = channel.GetDeviceInfo()
        print(device_info.Description)

        channel_config = channel.LoadMotorConfiguration(channel.DeviceID)
        chan_settings = channel.MotorDeviceSettings

        channel.GetSettings(chan_settings)

        channel_config.DeviceSettingsName = "HDR50/M"
        channel_config.UpdateCurrentConfiguration()

        channel.SetSettings(chan_settings, True, False)

        print("Homing Motor")
        channel.Home(60000)
        print("Homing Completed")

        step_size = float(pos_num)
        time.sleep(2)
        channel.MoveTo(Decimal(step_size), 60000)
        final_position = str(channel.DevicePosition)
        print(f"Position = {final_position}")
        time.sleep(2)

        return {
            "channel": int(channel_num),
            "target": step_size,
            "position": final_position,
        }

    except Exception as e:
        raise RuntimeError(f"Move failed on channel {channel_num}: {e}") from e
    finally:
        if channel is not None:
            try:
                channel.StopPolling()
            except Exception:
                pass
        if device is not None:
            try:
                device.Disconnect()
            except Exception:
                pass


def home_motor(channel_num):
    device = None
    channel = None
    try:
        DeviceManagerCLI.BuildDeviceList()

        device = BenchtopStepperMotor.CreateBenchtopStepperMotor(SERIAL_NO)
        device.Connect(SERIAL_NO)
        time.sleep(0.25)

        channel = device.GetChannel(channel_num)

        if not channel.IsSettingsInitialized():
            channel.WaitForSettingsInitialized(10000)
            assert channel.IsSettingsInitialized() is True

        channel.StartPolling(250)
        time.sleep(0.25)
        channel.EnableDevice()
        time.sleep(0.25)

        device_info = channel.GetDeviceInfo()
        print(device_info.Description)

        channel_config = channel.LoadMotorConfiguration(channel.DeviceID)
        chan_settings = channel.MotorDeviceSettings

        channel.GetSettings(chan_settings)

        channel_config.DeviceSettingsName = "HDR50/M"
        channel_config.UpdateCurrentConfiguration()

        channel.SetSettings(chan_settings, True, False)

        print("Homing Motor")
        channel.Home(60000)
        print("Homing Completed")

        return True

    except Exception as e:
        raise RuntimeError(f"Home failed on channel {channel_num}: {e}") from e
    finally:
        if channel is not None:
            try:
                channel.StopPolling()
            except Exception:
                pass
        if device is not None:
            try:
                device.Disconnect()
            except Exception:
                pass


def return_motor_info(channel_num):
    device = None
    channel = None
    try:
        DeviceManagerCLI.BuildDeviceList()

        device = BenchtopStepperMotor.CreateBenchtopStepperMotor(SERIAL_NO)
        device.Connect(SERIAL_NO)
        time.sleep(0.25)

        channel = device.GetChannel(channel_num)

        if not channel.IsSettingsInitialized():
            channel.WaitForSettingsInitialized(10000)
            assert channel.IsSettingsInitialized() is True

        channel.StartPolling(250)
        time.sleep(0.25)
        channel.EnableDevice()
        time.sleep(0.25)

        device_info = channel.GetDeviceInfo()
        print(device_info.Description)

        info = {
            "channel": int(channel_num),
            "description": str(device_info.Description),
            "device_id": str(channel.DeviceID),
            "position": str(channel.DevicePosition),
            "is_enabled": bool(channel.IsEnabled),
        }

        return info

    except Exception as e:
        raise RuntimeError(f"Status query failed on channel {channel_num}: {e}") from e
    finally:
        if channel is not None:
            try:
                channel.StopPolling()
            except Exception:
                pass
        if device is not None:
            try:
                device.Disconnect()
            except Exception:
                pass


def connect_to_all(channels=None):
    connected_channels = []
    device = None

    try:
        if channels is None:
            channels = DEFAULT_CHANNELS

        DeviceManagerCLI.BuildDeviceList()

        device = BenchtopStepperMotor.CreateBenchtopStepperMotor(SERIAL_NO)
        device.Connect(SERIAL_NO)
        time.sleep(0.25)

        for channel_num in channels:
            channel = device.GetChannel(int(channel_num))

            if not channel.IsSettingsInitialized():
                channel.WaitForSettingsInitialized(10000)
                assert channel.IsSettingsInitialized() is True

            channel.StartPolling(250)
            time.sleep(0.25)
            channel.EnableDevice()
            time.sleep(0.25)
            connected_channels.append(channel)

        return True

    except Exception as e:
        print(e)
        return False
    finally:
        for channel in connected_channels:
            try:
                channel.StopPolling()
            except Exception:
                pass
        if device is not None:
            try:
                device.Disconnect()
            except Exception:
                pass

def motor_position(channel_num, pos_num):
    device = None
    channel = None
    try:
        DeviceManagerCLI.BuildDeviceList()

        device = BenchtopStepperMotor.CreateBenchtopStepperMotor(SERIAL_NO)
        device.Connect(SERIAL_NO)
        time.sleep(0.25)

        channel = device.GetChannel(channel_num)

        if not channel.IsSettingsInitialized():
            channel.WaitForSettingsInitialized(10000)
            assert channel.IsSettingsInitialized() is True

        channel.StartPolling(250)
        time.sleep(0.25)
        channel.EnableDevice()
        time.sleep(0.25)

        device_info = channel.GetDeviceInfo()
        print(device_info.Description)

        channel_config = channel.LoadMotorConfiguration(channel.DeviceID)
        chan_settings = channel.MotorDeviceSettings

        channel.GetSettings(chan_settings)

        channel_config.DeviceSettingsName = "HDR50/M"
        channel_config.UpdateCurrentConfiguration()

        channel.SetSettings(chan_settings, True, False)

        return channel.DevicePosition

    except Exception as e:
        raise RuntimeError(f"Home failed on channel {channel_num}: {e}") from e
    finally:
        if channel is not None:
            try:
                channel.StopPolling()
            except Exception:
                pass
        if device is not None:
            try:
                device.Disconnect()
            except Exception:
                pass

def scan(x_pos, y_pos, z_pos, x_step_size, y_step_size, z_step_size):
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
        channel.Home(60000)
        print("Homing Completed")
        print("Homing Motor for channel 2")
        channel_2.Home(60000)
        print("Homing Completed")
        channel_3.Home(60000)
        print("Homing Completed")
        time.sleep(2)
        z_itr=int(z_pos/z_step_size)+1
        x_itr=int(x_pos/x_step_size)+1
        y_itr=int(y_pos/y_step_size)+1
        for N in range(z_itr):
            channel_3.MoveTo(Decimal(z_step_size*N), 60000)
            print(f"Channel 3 position changed. Position = {channel_3.DevicePosition}")
            for N in range(x_itr):
                print("Moving...")
                channel.MoveTo(Decimal(x_step_size*N), 60000)
                print(f"Channel 1 position changed. Position = {channel.DevicePosition}")
                for N in range (y_itr):
                    channel_2.MoveTo(Decimal(y_step_size*N), 60000)
                    print(f"Channel 2 position changed. Position = {channel_2.DevicePosition}")
                    time.sleep(1)
                #x_pos = channel.DevicePosition
                #y_pos = channel_2.DevicePosition

                    N=N+1
                #test_picoscope.picoscope_block_mode_run()  # run the picoscope example to show that the two can be used together without issue
                time.sleep(2)
                N=N+1
            N=N+1
        #Home after moving 
        channel.Home(60000)
        channel_2.Home(60000)
        channel_3.Home(60000)
        # Stop Polling and Disconnect
        channel.StopPolling()
        channel_2.StopPolling()
        channel_3.StopPolling()

        device.Disconnect()

    except Exception as e:
        # this can be bad practice: It sometimes obscures the error source
        print(e)

