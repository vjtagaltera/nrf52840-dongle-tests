#!/usr/bin/env python

import serial, threading, time

class SerReader(threading.Thread):
    def __init__(self, ser):
        super().__init__()
        self._ser = ser
        self._enable_read = None
        self._stopped = None
        self._stop_requested = None
        self._received_raw_bytes = bytearray(0)

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

    def get_data(self, timeout=1.0, up_to_bytes=244, up_to_char=b'\n'):
        self._received_raw_bytes = bytearray(0)
        tm0 = time.time()
        self._enable_read = True
        runcnt = 0 # index to next char to process
        while True:
            dlen = len(self._received_raw_bytes)
            ending_char_found = False
            if dlen > runcnt:
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
        return self._received_raw_bytes


ser = serial.Serial('COM6:', 115200, timeout=0.01)
print("  name: ", ser.name)
rxthread = SerReader(ser)
rxthread.start()

data_len = 480 # less than 244*2=488
data = ''
data_seg = ''
for i in range(0, data_len, 5):
    data_seg = ("x%4d" % (i+5)).replace(' ', '_')
    data += data_seg
data += "\n" # trigger sending on the device

tm0=time.time()
ser.write(data.encode())
tm1=time.time()
while True:
    rv = rxthread.get_data(timeout=0.5)
    tm2=time.time()
    if len(rv) > 0:
        print("  %.2f rv: " % ( tm2 - tm0 ), len(rv), rv)
        if rv.find(data_seg.encode()) > 0:
            print("Data ending seg found")
            break
    if tm2 - tm1 > 3:
        break
    time.sleep(0.010)

ser.close()

print("  %.2f for write. %.2f to finish. rate %.3f " % (
        tm1-tm0, tm2-tm0, data_len*2/(tm2-tm0) ))
print("  data written ", data)

