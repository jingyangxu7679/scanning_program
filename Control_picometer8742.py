import sys
import os
import inspect
# Import the .NET Common Language Runtime (CLR) to allow interaction with .NET
import clr
import numpy as np

print ("Python %s\n\n" % (sys.version,))

strCurrFile = os.path.abspath (inspect.stack()[0][1])
print ("Executing File = %s\n" % strCurrFile)

# Initialize the DLL folder path to where the DLLs are located
strPathDllFolder = os.path.dirname (strCurrFile)
print ("Executing Dir  = %s\n" % strPathDllFolder)

# Add the DLL folder path to the system search path (before adding references)
sys.path.append (strPathDllFolder)

# Add a reference to each .NET assembly required
clr.AddReference ("UsbDllWrap")

# Import a class from a namespace
from Newport.USBComm import *
from System.Text import StringBuilder
from System.Collections import Hashtable
from System.Collections import IDictionaryEnumerator

def get_z_focus(x_current, initial_pos, initial_z_focus):
    x_current = float(str(x_current)) * 0.1  # convert to mm for the stage
    #z_focus = initial_z_focus + 3112 * (x_current - initial_pos)
    z_focus = initial_z_focus + 150 * (x_current - initial_pos)
    z_relative=150 * (x_current - initial_pos)
    #return z_focus
    return z_relative
def get_x_focus_xy(x_current, y_current, initial_pos_X, initial_pos_Y, initial_z_focus):
    # Placeholder function for future implementation
    x_current=float(str(x_current)) * 0.1
    y_current=float(str(y_current)) * 0.1
    z_focus=-70.3+2455.53*(x_current-initial_pos_X)+3175.58*(y_current-initial_pos_Y)
    return z_focus

def adjust_focus(x_current, y_current, initial_pos_X, initial_pos_Y, initial_z_focus):
    z_focus = get_x_focus_xy(x_current, y_current, initial_pos_X, initial_pos_Y, initial_z_focus)
    # Code to move the stage to the new z_focus position would go here
    print(f"Adjusting focus to z={z_focus} based on x={x_current}")
    # Call the class constructor to create an object
    oUSB = USB (True)

    # Discover all connected devices
    bStatus = oUSB.OpenDevices (0, True)

    if (bStatus) :
        oDeviceTable = oUSB.GetDeviceTable ()
        nDeviceCount = oDeviceTable.Count
        print ("Device Count = %d" % nDeviceCount)

        # If no devices were discovered
        if (nDeviceCount == 0) :
            print ("No discovered devices.\n")
        else :
            oEnumerator = oDeviceTable.GetEnumerator ()
            strDeviceKeyList = np.array ([])

            # Iterate through the Device Table creating a list of Device Keys
            for nIdx in range (0, nDeviceCount) :
                if (oEnumerator.MoveNext ()) :
                    strDeviceKeyList = np.append (strDeviceKeyList, oEnumerator.Key)

            print (strDeviceKeyList)
            print ("\n")

            strBldr = StringBuilder (64)

            # Iterate through the list of Device Keys and query each device with *IDN?
            for oDeviceKey in strDeviceKeyList :
                strDeviceKey = str (oDeviceKey)
                print (strDeviceKey)
                strBldr.Remove (0, strBldr.Length)
                nReturn = oUSB.Query (strDeviceKey, "*IDN?", strBldr)
                print ("Return Status = %d" % nReturn)
                print ("*IDN Response = %s\n" % strBldr.ToString ())#prints what have been stored in the buffer

                #Position=oUSB.Query (strDeviceKey, "4TP?", strBldr)
                target_steps = int(round(z_focus))      # convert numeric z_focus to integer steps
                #cmd = f"4PA{target_steps}"              # e.g. "4PA900"
                cmd = f"4PR{target_steps}"              # e.g. "4PA900"

                strBldr.Remove(0, strBldr.Length)
                nReturn2 = oUSB.Query(strDeviceKey, cmd, strBldr)
                print("Sent:", cmd)
                print("Return Status =", nReturn2)
                #nReturn2 = oUSB.Query(strDeviceKey, "4PA900", strBldr)
                print("Return Status = %d" % nReturn2)
                print("Move Response = %s" % strBldr.ToString())

    #            print ("Position = %s\n" % Position)
    else :
        print ("\n***** Error:  Could not open the devices. *****\n\nCheck the log file for details.\n")

    # Shut down all communication
    oUSB.CloseDevices ()
    print ("Devices Closed.\n")
