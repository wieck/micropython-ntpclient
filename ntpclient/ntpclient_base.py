# ntpclient_base.py

import sys
import usocket as socket
import ustruct as struct
from machine import RTC, Pin
import uasyncio as asyncio
import utime

# (date(2000, 1, 1) - date(1900, 1, 1)).days * 24*60*60
NTP_DELTA = 3155673600
# (date(2000, 1, 1) - date(1970, 1, 1)).days * 24*60*60
UNIX_DELTA = 946684800

# Poll and adjust intervals
MIN_POLL = 64           # never poll faster than every 32 seconds
MAX_POLL = 1024         # default maximum poll interval
ADJ_INTERVAL = 2        # interval in seconds to call adjtime()

# time_add_us() -
#   Adds a number of microseconds to a timestamp.
#   Returns a timestamp.
#
#   Internally we use a struct tm based timestamp format, which is
#   a tuple composed of (sec, usec) based on epoch 2000-01-01.
def time_add_us(ts, us):
    usec = ts[1] + us
    if usec < 0:
        usec = usec - 1000000
    sec = ts[0] + int(usec / 1000000)
    return (sec, usec % 1000000)

# time_diff_us() -
#   Subtracts ts2 from ts1.
#   Returns the difference in microseconds.
def time_diff_us(ts1, ts2):
    return (ts1[0] - ts2[0]) * 1000000 + (ts1[1] - ts2[1])

# ntpclient -
#   Class implementing the uasyncio based NTP client
class ntpclient_base:
    def __init__(self, host = 'pool.ntp.org', poll = MAX_POLL,
                 max_startup_delta = 1, debug = False):
        self.host = host
        self.sock = None
        self.addr = None
        self.rstr = None
        self.wstr = None
        self.req_poll = poll
        self.poll = MIN_POLL
        self.max_startup_delta = int(max_startup_delta * 1000000)
        self.rtc = RTC()
        self.debug = debug

        asyncio.create_task(self._poll_task())
        asyncio.create_task(self._adj_task())

    async def _poll_server(self):
        # We try to stay with the same server as long as possible. Only
        # lookup the address on startup or after errors.
        if self.sock is None:
            self.addr = socket.getaddrinfo(self.host, 123)[0][-1]
            if self.debug:
                print("ntpclient: new server address:", self.addr)

            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.connect(self.addr)

            self.rstr = asyncio.StreamReader(self.sock)
            self.wstr = asyncio.StreamWriter(self.sock)

        # Send the NTP v3 request to the server
        wbuf = bytearray(48)
        wbuf[0] = 0b00011011
        start_ticks = utime.ticks_us()
        self.wstr.write(wbuf)
        await self.wstr.drain()

        # Get the server reply
        try:
            rbuf = await asyncio.wait_for(self.rstr.read(48), 0.5)
        except asyncio.TimeoutError:
            raise Exception("timeout receiving from server")

        # Record the microseconds it took for this NTP round trip
        roundtrip_us = utime.ticks_diff(utime.ticks_us(), start_ticks)

        # Record the current time as a (sec, usec) tuple
        now = self.rtc.datetime()
        dtnow = (now[0], now[1], now[2], now[4], now[5], now[6], 0, 0)
        if sys.platform == 'esp32':
            tnow = (utime.mktime(dtnow), now[7])
        elif sys.platform == 'esp8266':
            tnow = (utime.mktime(dtnow), now[7] * 1000)
        else:
            raise RuntimeError("unsupported platform '{}'".format(sys.platform))

        # Get the server's receive and send timestamps in (sec, frac)
        # tuple format (epoch = 1900)
        d1 = struct.unpack("!II", rbuf[32:40])
        d2 = struct.unpack("!II", rbuf[40:48])

        # Extract the four relevant timestamp tuples from the reply
        # t0 = client side transmit time (we actually sent 1900-01-01)
        # t1 = server side receive time
        # t2 = server side transmit time
        # t3 = client side receive time (based on that sent time ^^^^)
        #t0 = (0,0)
        t1 = (d1[0] - NTP_DELTA, int(d1[1] / 4294.967))
        t2 = (d2[0] - NTP_DELTA, int(d2[1] / 4294.967))
        #t3 = (0, roundtrip_us)

        # Calculate the delay (round trip minus time spent on the server)
        delay = (roundtrip_us - time_diff_us(t2, t1))

        # Return the result of this measurement as (delay, delta, ts2)
        # tuple. Delay and delta are in microseconds, ts2 is (sec, usec).
        return (delay, time_diff_us(tnow, t2), t2)

    async def _poll_task(self):
        # Needs to be implemented per platform
        pass

    async def _adj_task(self):
        # Needs to be implemented per platform
        pass
