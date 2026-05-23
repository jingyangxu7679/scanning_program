import instruments as ik
#https://everypinio.github.io/python-instruments-library/instruments-database/motor-controllers/newport/picomotorcontroller-8742/
# Define the IP address and port of the controller
ip = "101947"
port = 23

# Open a TCP/IP connection to the controller
controller = ik.newport.PicoMotorController8742.open_usb()

# Set the controller address (if using multiple controllers)
controller.controller_address = 1

# Get the first axis of the controller
axis = controller.axis[4]

# Move the motor relative to its current position
axis.move_relative = 100

# Close the connection to the controller
controller.close()