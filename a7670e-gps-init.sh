
#!/bin/bash

# Script to initialize the A7670E HAT for gpsd

SERIAL_PORT="/dev/serial0"

# 1. Power on the GNSS module
echo -e "AT+CGNSSPWR=1\r\n" > $SERIAL_PORT
sleep 1

# 2. Enable information output
echo -e "AT+CGNSSTST=1\r\n" > $SERIAL_PORT

# 3. Start the  NMEA Data Stream
echo -e "AT+CGNSSPORTSWITCH=0,1\r\n" > $SERIAL_PORT