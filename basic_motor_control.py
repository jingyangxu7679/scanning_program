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
DEFAULT_CHANNELS = (1, 2, 3)
connected_channels = []
connected_device = None
connected_channel_map = {}

#connect to all three channels once opening the GUI
def connect_to_all_channels(channels=None):
    global connected_device
    global connected_channels
    global connected_channel_map

    try:
        if channels is None:
            channels = DEFAULT_CHANNELS

        requested_channels = [int(ch) for ch in channels]

        # Reuse an existing connection if all requested channels are already available.
        if connected_device is not None and all(ch in connected_channel_map for ch in requested_channels):
            return True

        # Reset partially-open state before reconnecting.
        disconnect_all_channels()

        DeviceManagerCLI.BuildDeviceList()

        device = BenchtopStepperMotor.CreateBenchtopStepperMotor(SERIAL_NO)
        device.Connect(SERIAL_NO)
        time.sleep(0.25)

        local_channels = []
        local_channel_map = {}

        for channel_num in requested_channels:
            channel = device.GetChannel(int(channel_num))

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

            local_channels.append(channel)
            local_channel_map[int(channel_num)] = channel

        connected_device = device
        connected_channels = local_channels
        connected_channel_map = local_channel_map

        return True

    except Exception as e:
        disconnect_all_channels()
        print(e)
        return False

#need to home all motors before disconnecting to ensure they are in a known state when the next connection is made
def disconnect_all_channels():
    global connected_device
    global connected_channels
    global connected_channel_map
    N=1
    for channel in connected_channels:
        try:
            home_motor(N)
            channel.StopPolling()
            N=N+1
        except Exception:
            pass

    if connected_device is not None:
        try:
            connected_device.Disconnect()
        except Exception:
            pass

    connected_device = None
    connected_channels = []
    connected_channel_map = {}


def _get_connected_channel(channel_num):
    if connected_device is None:
        ok = connect_to_all_channels()
        if not ok:
            raise RuntimeError("Unable to connect to motor controller")

    channel = connected_channel_map.get(int(channel_num))
    if channel is None:
        ok = connect_to_all_channels((1, 2, 3))
        if not ok:
            raise RuntimeError(f"Unable to connect channel {channel_num}")
        channel = connected_channel_map.get(int(channel_num))

    if channel is None:
        raise RuntimeError(f"Channel {channel_num} is not connected")

    return channel

# IP address is not used for Kinesis USB control; kept for compatibility with existing callers.
def single_move(_ip_addr, channel_num, pos_num):
    try:
        channel_in = _get_connected_channel(channel_num)

        print("Homing Motor")
        channel_in.Home(60000)
        print("Homing Completed")

        step_size = float(pos_num)
        time.sleep(2)
        channel_in.MoveTo(Decimal(step_size), 60000)
        final_position = str(channel_in.DevicePosition)
        print(f"Position = {final_position}")
        time.sleep(2)

        return {
            "channel": int(channel_num),
            "target": step_size,
            "position": final_position,
        }

    except Exception as e:
        raise RuntimeError(f"Move failed on channel {channel_num}: {e}") from e


def connect_and_move(_ip_addr, channel_num, pos_num):
    return single_move(_ip_addr, channel_num, pos_num)


def home_motor(channel_num):
    try:
        channel_in = _get_connected_channel(channel_num)

        print("Homing Motor")
        channel_in.Home(60000)
        print("Homing Completed")

        return True

    except Exception as e:
        raise RuntimeError(f"Home failed on channel {channel_num}: {e}") from e


def return_motor_info(channel_num):
    try:
        channel = _get_connected_channel(channel_num)

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


def connect_to_all(channels=None):
    return connect_to_all_channels(channels)


def connect_to_all_Channels(channels=None):
    return connect_to_all_channels(channels)

def motor_position(channel_num, pos_num):
    try:
        channel = _get_connected_channel(channel_num)

        return channel.DevicePosition

    except Exception as e:
        raise RuntimeError(f"Home failed on channel {channel_num}: {e}") from e

def scan(x_pos, y_pos, z_pos, x_step_size, y_step_size, z_step_size):
    # Comment out this line for the real device
    #SimulationManager.Instance.InitializeSimulations()
    try:
        channel = _get_connected_channel(1)
        channel_2 = _get_connected_channel(2)
        channel_3 = _get_connected_channel(3)

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

    except Exception as e:
        raise RuntimeError(f"Scan failed: {e}") from e

