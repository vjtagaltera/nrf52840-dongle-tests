#!/usr/bin/env python

import serial.tools.list_ports
import re
import serial, threading, time, copy
import sliplib


def extract_vid_pid(info_string):
    """
    Try different methods of extracting vendor and product IDs from a string.

    The output from serial.tools.list_ports.comports() varies so
    widely from machine to machine and OS to OS, the only option we
    have right now is to add to a list of patterns that we have seen so
    far and compare the output.

    info_string -- the string possibly containing vendor and product IDs.

    Returns a tuple of (vendor ID, product ID) if a device is found.
    If an ID isn't found, returns None.

    The code is adapted from pygatt/backends/bgapi/util.py .

    Example info_string:
        device  USB VID:PID=1915:520F SER=C2FA1DDFB5D5 LOCATION=1-3:x.0 COM9 USB Serial Device (COM9)
        device  USB VID:PID=1915:520F SER=C01234778899 LOCATION=1-8:x.0 COM10 USB Serial Device (COM10)
    """

    DEVICE_STRING_PATTERNS = [
        # '...VID:PID=XXXX:XXXX SER=XXXXXXXXXXXX...'
        re.compile('.*VID:PID=([0-9A-Fa-f]{0,4}):([0-9A-Fa-f]{0,4}).*SER=([0-9A-Fa-f]{0,12}).*'),

        # '...VID_XXXX...PID_XXXX SER=XXXXXXXXXXXX...'
        re.compile('.*VID_([0-9A-Fa-f]{0,4}).*PID_([0-9A-Fa-f]{0,4}).*SER=([0-9A-Fa-f]{0,12}).*')
    ]

    for p in DEVICE_STRING_PATTERNS:
        match = p.match(info_string)
        if match:
            return int(match.group(1), 16), int(match.group(2), 16), str(match.group(3)).lower()
    return None


class USBSerialDeviceInfo(object):
    pass


devices = serial.tools.list_ports.comports()

found_port = None
for device in devices:
        dev = USBSerialDeviceInfo()
        dev.port_name = device[0]
        dev.device_name = device[1]
        found_device = extract_vid_pid(device[2])

        print(" device: ", found_device, " port: ", dev.port_name, " name: ", dev.device_name)
        # device:  (6421, 21007, 'c01122334455')  port:  COM11  name:  USB Serial Device (COM11)
        if type(found_device) is tuple and len(found_device) == 3:
            if 0x1915 == found_device[0] and 0x520F == found_device[1]:
                dev.ser = found_device[2]
                if found_port is None:
                    found_port = [dev]
                else:
                    found_port.append(dev)

working_port = None
if found_port is not None:
    for port in found_port:
        print(" found_port: ", port.port_name, port.ser, port.device_name)
        if working_port is None:
            working_port = port
else:
    print(" found_port: none")

# --------
# adapt from serialtest1.py:

class SerReader(threading.Thread):
    def set_stop(self):
        self._stop_requested = True
    def wait_stopped(self):
        for i in range(50):  # 50 * 20ms = 1sec
            if self._stopped:
                break
            time.sleep(0.02) # 20ms

    def __init__(self, ser):
        super().__init__()
        self._ser = ser
        self._enable_read = None
        self._stopped = None
        self._stop_requested = None
        self._received_raw_bytes = bytearray(0)
        self._returned_raw_bytes = bytearray(0)

    def run(self):
        while True:
            if self._stop_requested == True:
                break
            rv = b''
            if self._enable_read == True:
                rv = self._ser.read(1024)
            if len(rv) > 0:
                self._received_raw_bytes.extend(bytearray(rv))
            elif self._ser.is_open:
                time.sleep(0.001)
            else:
                print("Break due to ser closed")
                break
        self._stopped = True

    def get_data(self, timeout=1.0, up_to_bytes=512, up_to_char=None): # up_to_char=b'\n'
        if len(self._received_raw_bytes) != len(self._returned_raw_bytes):
            print("Discard bytes: ", " _received_raw_bytes", len(self._received_raw_bytes),
                  " _returned_raw_bytes", len(self._returned_raw_bytes))
        self._received_raw_bytes = bytearray(0)
        tm0 = time.time()
        self._enable_read = True
        runcnt = 0 # index to next char to process
        while True:
            dlen = len(self._received_raw_bytes)
            ending_char_found = False
            if dlen > runcnt and up_to_char is not None:
                for i in range(runcnt, dlen):
                    runcnt = i+1
                    thechar = self._received_raw_bytes[i]
                    if thechar == up_to_char[0]:
                        ending_char_found = True
                        break
            if ending_char_found:
                print("  break due to ending char found  ")
                break
            if dlen >= up_to_bytes:
                print("  break due to number of bytes  ")
                break
            if time.time() > tm0 + timeout:
                print("  break due to timeout  ")
                break
            time.sleep(0.010)
        self._enable_read = False
        self._returned_raw_bytes = copy.deepcopy(self._received_raw_bytes)
        return self._returned_raw_bytes


port_file_name = '%s:' % working_port.port_name [0:5] # max 5 chars. so COM11: is COM11
ser = serial.Serial(port_file_name, 115200, timeout=0.01)
print(" working on port name: ", ser.name, "  ser: ", working_port.ser)
rxthread = SerReader(ser)
rxthread.start()

data_len = 20 # less than 244*2=488
data = ''
data_seg = ''
for i in range(0, data_len, 5):
    data_seg = ("x%4d" % (i+5)).replace(' ', '_')
    data += data_seg
data += "\n" # trigger sending on the nrf device

#data = b'\xC0' + data.encode() + b'\xC0' # 0xC0 is SLIP escape
data = sliplib.encode(data.encode())
print(" data len: ", len(data))

tm0=time.time()
ser.write(data)
tm1=time.time()
while True:
    rv = rxthread.get_data(timeout=0.5)
    tm2=time.time()
    if len(rv) > 0:
        print("  %.2f rv: " % ( tm2 - tm0 ), len(rv), rv)
        ptr = 0
        dlen = len(rv)
        while ptr <= dlen:
            idx = rv.find(sliplib.END, ptr)
            if idx < 0:
                rv = rv[ptr:]
                print(" Drop: ", len(rv))
                break
            if idx >= 0:
                if idx < dlen and idx >= ptr:
                    pkt_raw = rv[ptr:idx+1]
                    rlen = idx+1 - ptr
                    if sliplib.is_valid(pkt_raw):
                        pkt = sliplib.decode(pkt_raw)
                        print(" Decoded: ", len(pkt), pkt)
                    else:
                        print(" Error decoding: ", len(pkt), pkt)
                    ptr += rlen
                else:
                    print(" Error: searching for sliplib.END ")
                    break
        if rv.find(data_seg.encode()) > 0:
            print("Data ending seg found")
            break
    if tm2 - tm1 > 12: # 12: test duration 12 seconds
        break
    time.sleep(0.010)

rxthread.set_stop()
tm3 = time.time()
rxthread.wait_stopped()
tm4 = time.time()

ser.close()

print("")
print("  %.2f for write. %.2f to finish. rate %.3f " % (
        tm1-tm0, tm2-tm0, data_len*2/(tm2-tm0) ))
print("  data written ", data)
print("  wait_stop used %.2f" % (tm4-tm3))

