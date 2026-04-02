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



