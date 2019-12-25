# ntpclient.py

import sys
import usocket as socket
import ustruct as struct
from machine import RTC, Pin
import uasyncio as asyncio
import utime
import gc

# (date(2000, 1, 1) - date(1900, 1, 1)).days * 24*60*60
NTP_DELTA = 3155673600
# (date(2000, 1, 1) - date(1970, 1, 1)).days * 24*60*60
UNIX_DELTA = 946684800

MIN_POLL = 64
MAX_POLL = 1024

# Internally we use a struct tm based timestamp format, which is
# a tuple composed of (sec, usec) based on epoch 2000-01-01.

# time_add_us() -
#   Adds a number of microseconds to a timestamp.
#   Returns a timestamp.
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
class ntpclient:
    def __init__(self, host = 'pool.ntp.org', poll = MAX_POLL,
                 adj_interval = 2, debug = False,
                 max_startup_delta = 1.0):
        self.host = host
        self.sock = None
        self.addr = None
        self.rstr = None
        self.wstr = None
        self.req_poll = poll
        self.poll = MIN_POLL
        self.max_startup_delta = int(max_startup_delta * 1000000)
        self.rtc = RTC()
        self.last_delta = None
        self.drift_hist = None
        self.adj_delta = 0
        self.adj_interval = adj_interval
        self.adj_hist = [100000,-100000,0]
        self.adj_sum = 0
        self.adj_num = 0
        self.debug = debug

        asyncio.create_task(self._poll_task())
        asyncio.create_task(self._adj_task())

    async def _poll_server(self):
        # Send the NTP v3 request to the server
        wbuf = bytearray(48)
        wbuf[0] = 0b00011011
        start_ticks = utime.ticks_us()
        self.wstr.write(wbuf)
        await self.wstr.drain()
        del wbuf

        # Get the server reply
        rbuf = await self.rstr.read(48)

        # Record the microseconds it took for this NTP round trip
        roundtrip_us = utime.ticks_diff(utime.ticks_us(), start_ticks)

        # Record the current time as a (sec, usec) tuple
        now = self.rtc.datetime()
        dtnow = (now[0], now[1], now[2], now[4], now[5], now[6], 0, 0)
        tnow = (utime.mktime(dtnow), now[7])

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
        # We try to stay with the same server as long as possible. Only
        # lookup the address on startup or after errors.
        if self.sock is None:
            self.addr = socket.getaddrinfo(self.host, 123)[0][-1]
            if self.debug:
                print("ntpclient: new server address:", self.addr)

            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(0.2)
            self.sock.connect(self.addr)

            self.rstr = asyncio.StreamReader(self.sock)
            self.wstr = asyncio.StreamWriter(self.sock)

        # Try to get a first server reading
        while True:
            try:
                current = await self._poll_server()
            except Exception as ex:
                print('ntpclient: _poll_task():', str(ex))
                self.sock.close()
                self.sock = None
                self.addr = None
                await asyncio.sleep(10)
                continue
            break

        # If our RTC is more than max_startup_delta off from the server's
        # time, we hard set it. Otherwise we let the slew algorithm deal
        # with it.
        ts_now = time_add_us(current[2], current[0] // 2)
        r = self.rtc.datetime()
        ts_rtc = (utime.mktime((r[0], r[1], r[2],
                                r[4], r[5], r[6], 0, 0)), r[7])
        rtc_diff_us = time_diff_us(ts_now, ts_rtc)
        if rtc_diff_us > self.max_startup_delta:
            now = utime.localtime(ts_now[0])
            if self.debug:
                print("ntpclient: RTC delta too large, setting rtc to", now)
            self.rtc.init((now[0], now[1], now[2], now[6],
                           now[3], now[4], now[5], ts_now[1]))
            self.last_delta = None

        # Main client loop
        while True:
            # We calculate the next polling interval to sit on a 300ms
            # boundary in the hope that this might be a quiet asyncio
            # time so nothing interferes with the time critical server
            # communication.
            wait_ms = (self.poll - 8) * 1000
            wait_ms += (1300000 - self.rtc.datetime()[7]) // 1000
            await asyncio.sleep_ms(wait_ms)
            del wait_ms

            # Poll the server 5 times and record the deltas.
            try:
                deltas = []
                for i in range(0, 5):
                    if i > 0:
                        await asyncio.sleep(2)
                    current = await self._poll_server()
                    deltas.append(current[1] - current[0] // 2)
            except Exception as ex:
                print('ntpclient: _poll_task():', str(ex))
                self.sock.close()
                self.sock = None
                self.addr = None
                await asyncio.sleep(10)
                continue

            # Discard the min and max and calculate the average of the
            # remaining 3 results as our current delta. Together with
            # the last delta this allows us to calculate the drift of
            # our RTC and the required delta to feed into adjtime(3)
            # in the _adj_task() to slew the RTC.
            delta = -sum(sorted(deltas)[1:3]) // 3
            adj_sum = self.adj_sum
            if self.last_delta is None:
                # This was the first actual average delta we got from this
                # server. Remember it and start over.
                self.last_delta = delta
                continue

            corr = delta - self.last_delta
            self.last_delta = delta
            drift = (self.adj_sum + corr) // self.adj_num
            if self.drift_hist is None:
                self.drift_hist = [drift] * 3
            else:
                self.drift_hist = self.drift_hist[1:] + [drift]
            avg_drift = sum(self.drift_hist) // len(self.drift_hist)
            self.adj_delta = avg_drift + delta // self.adj_num * 3 // 4

            # Depending on how close together or spread out our last
            # 3 adj_delta values were we may increase or decrease
            # the polling interval.
            self.adj_hist = self.adj_hist[1:] + [self.adj_delta] 
            adj_spread = max(self.adj_hist) - min(self.adj_hist)
            if self.poll < self.req_poll:
                if adj_spread < 5 * self.adj_interval:
                    self.poll <<= 1
            elif self.poll > MIN_POLL:
                if adj_spread > 20 * self.adj_interval:
                    self.poll >>= 1
            if self.debug:
                print("ntpclient: state at", utime.localtime())
                print("ntpclient: deltas:", deltas,
                      "delta:", delta)
                print("ntpclient: corr:", corr, "drift:", drift,
                      "drift_hist:", self.drift_hist)
                print("ntpclient: avg_drift:", avg_drift,
                      "new adj_delta:", self.adj_delta)
                print("ntpclient: adj_hist:", self.adj_hist,
                      "new poll:", self.poll)
                print("----")
            self.adj_sum = 0
            self.adj_num = 0

            # Cleanup
            del deltas, delta, adj_sum, corr, drift, avg_drift, adj_spread
            del current

    async def _adj_task(self):
        # This task slimply calls adjtime() every adj_interval seconds
        # and sums up how much of a total slew it produced in how many
        # calls. The poll_task will use this feedback data in calculating
        # the new delay.
        while True:
            await asyncio.sleep(self.adj_interval)
            if self.adj_delta != 0:
                delta = self.adj_delta
                utime.adjtime((0, delta))
                self.adj_sum += delta
                del delta
            self.adj_num += 1
