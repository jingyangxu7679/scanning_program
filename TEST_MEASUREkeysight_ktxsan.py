"""
keysight_ktxsan Python API Example Program

Creates a driver object, reads a few DriverIdentity interface properties, and checks
the instrument error queue.  May include additional instrument specific functionality.

Runs in simulation mode without an instrument.

Requires Python 3.6 or newer and keysight_ktxsan Python module installed.
"""

import keysight_ktxsan
import numpy as np # For keysight_ktxsan arrays


def main():
    """
    Edit resource_name and options as needed.  resource_name is ignored if option Simulate=true
    For this example, resource_name may be a VISA address(e.g. "TCPIP0::<IP_Address>::INSTR")
    or a VISA alias.  For more information on using VISA aliases, refer to the Keysight IO
    Libraries Connection Expert documentation.
    """
    #resource_name = "MyVisaAlias"
    resource_name = "TCPIP0::169.254.253.122::5025::SOCKET"
    #resource_name = "TCPIP0::169.254.253.122::inst0::INSTR"
    #  Edit the initialization options as needed
    idQuery = True
    reset   = True
    options = "QueryInstrStatus=False, Simulate=False, Trace=False"

    try:
        print("\n  keysight_ktxsan Python API Example1\n")

        # Call driver constructor with options
        global driver # May be used in other functions
        driver = None
        driver = keysight_ktxsan.KtXSAn(resource_name, idQuery, reset, options)
        print("Driver Initialized")

        #  Print a few identity properties
        print('  identifier: ', driver.identity.identifier)
        print('  revision:   ', driver.identity.revision)
        print('  vendor:     ', driver.identity.vendor)
        print('  description:', driver.identity.description)
        print('  model:      ', driver.identity.instrument_model)
        print('  resource:   ', driver.driver_operation.io_resource_descriptor)
        print('  options:    ', driver.driver_operation.driver_setup)


        inVal1 = 55000005
        driver.frequency.center = inVal1
        outVal1 = driver.frequency.center
        print("\n Center Frequency is  : ", outVal1)

        rearTriggerNo = 1
        outVal3 = driver.MemoryOperation.QueryStorageDirectory()
        print("\n MemoryOperation StorageDirectory is : ", outVal3)


        # Check instrument for errors
        print()
        while True:
            outVal = ()
            outVal = driver.utility.error_query()
            print("  error_query: code:", outVal[0], " message:", outVal[1])
            if(outVal[0] == 0): # 0 = No error, error queue empty
                break

    except Exception as e:
        print("\n  Exception:", e.__class__.__name__, e.args)

    finally:
        if driver is not None: # Skip close() if constructor failed
            driver.close()
        input("\nDone - Press Enter to Exit")


if __name__ == "__main__":
    main()