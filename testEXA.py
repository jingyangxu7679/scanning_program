import keysight_ktxsan
import numpy as np # For keysight_ktxsan arrays
#need to run under python 3.10 version
import pyvisa
rm=pyvisa.ResourceManager()
resources=rm.list_resources()
print("Detected resources:", resources)
print(rm.visalib)
address="TCPIP0::169.254.253.122::5025::SOCKET" # IP address of the instrument
print("Connecting to instrument at address:", address)
inst=rm.open_resource(address)
inst.timeout=50000 # Set timeout to 5 seconds
try:
    print("Instrument ID:", inst.query("*IDN?"))
finally:
    inst.close()
    rm.close()