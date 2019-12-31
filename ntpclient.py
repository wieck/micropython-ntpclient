# ntpclient.py

import os
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

# Poll interval
_MIN_POLL = 64          # never poll faster than every 32 seconds
_MAX_POLL = 1024        # default maximum poll interval
_POLL_INC_AT = 50       # increase interval when the delta per second
                        # falls below this number of microseconds
_POLL_DEC_AT = 200      # decrease interval when the delta per second
                        # grows above this number

# Drift file configuration
_DRIFT_FILE_VERSION = 1
_DRIFT_NUM_MAX = 200    # Aggregate when we have this many samples
_DRIFT_NUM_AVG = 100    # Aggregate down to this many and save drift file

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
class ntpclient:
    def __init__(self, host = 'pool.ntp.org', poll = _MAX_POLL,
                 adj_interval = 2, debug = False,
                 max_startup_delta = 1.0, drift_file = None):
        self.host = host
        self.sock = None
        self.addr = None
        self.rstr = None
        self.wstr = None
        self.req_poll = poll
        self.poll = _MIN_POLL
        self.max_startup_delta = int(max_startup_delta * 1000000)
        self.rtc = RTC()
        self.last_delta = None
        self.drift_sum = 0
        self.drift_num = 0
        self.adj_delta = 0
        self.adj_interval = adj_interval
        self.adj_sum = 0
        self.adj_num = 0
        self.drift_file = drift_file
        self.debug = debug

        asyncio.create_task(self._poll_task())
        asyncio.create_task(self._adj_task())

    def drift_save(self):
        # This is called every time we increase the polling interval
        # or aggregate the drift summary data.
        if self.drift_file is None:
            return

        try:
            tmp = self.drift_file + '.tmp'
            with open(tmp, 'w') as fd:
                fd.write("version = {}\n".format(_DRIFT_FILE_VERSION))
                fd.write("drift_sum = {}\n".format(self.drift_sum))
                fd.write("drift_num = {}\n".format(self.drift_num))
            os.rename(tmp, self.drift_file)
        except Exception as ex:
            print("ntpclient: drift_save():", ex)
        if self.debug:
            print("ntpclient: saved {}".format(self.drift_file))

    def drift_load(self):
        if self.drift_file is None:
            return

        try:
            with open(self.drift_file, 'r') as fd:
                info = {}
                exec(fd.read(), globals(), info)
                if info['version'] > _DRIFT_FILE_VERSION:
                    print("ntpclient: WARNING - drift file version is {} "
                          "- expected {}".format(info['version'],
                                                 _DRIFT_FILE_VERSION))
                self.drift_sum = info['drift_sum']
                self.drift_num = info['drift_num']
        except Exception as ex:
            print("ntpclient: drift_load():", ex)
            return
        if self.debug:
            print("ntpclient: loaded drift data {}/{}"
                  " = {}".format(self.drift_sum, self.drift_num,
                                 self.drift_sum // self.drift_num))


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
        # Try loading an existing drift file
        self.drift_load()

        # Try to get a first server reading
        while True:
            try:
                current = await self._poll_server()
            except Exception as ex:
                print('ntpclient: _poll_task():', str(ex))
                self.sock.close()
                self.sock = None
                self.addr = None
                await asyncio.sleep(4)
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

            # Try to poll the server up to 3 times to get the current
            # delta between the server's and our clock.
            current = None
            try:
                for i in range(0, 3):
                    if i > 0:
                        await asyncio.sleep(2)
                    try:
                        current = await self._poll_server()
                    except Exception as ex:
                        print("ntpclient: {0}".format(ex))
                        continue
                    break
                if current is None:
                    raise Exception("3/3 packets lost")
                delta = -(current[1] - current[0] // 2)
            except Exception as ex:
                print("ntpclient: {0} - resetting connection".format(ex))
                self.sock.close()
                self.sock = None
                self.addr = None
                self.poll = _MIN_POLL
                continue

            if self.last_delta is None:
                # This was the first actual average delta we got from this
                # server. Remember it and start over.
                self.last_delta = delta
                continue

            corr = delta - self.last_delta
            self.last_delta = delta
            drift = (self.adj_sum + corr) // self.adj_num
            self.drift_sum += drift
            self.drift_num += 1
            if self.drift_num >= _DRIFT_NUM_MAX:
                # When we have 200 samples we aggregate the data down to
                # 100 samples in order to give an actual change in the
                # drift a chance to change our average.
                self.drift_sum = (self.drift_sum // self.drift_num) \
                                 * _DRIFT_NUM_AVG
                self.drift_num = _DRIFT_NUM_AVG
                self.drift_save()
                if self.debug:
                    print("ntpclient: drift average adjusted to {0}/{1}".format(
                          self.drift_sum, self.drift_num))

            avg_drift = self.drift_sum // self.drift_num
            self.adj_delta = avg_drift + delta // self.adj_num // 2

            # Adjust the poll interval when the measured adjustment
            # per adj_interval is below or above a certain threshold.
            # This means we poll less if we think we are close to
            # the server and more often while homing in.
            delta_per_sec = delta // self.adj_num // self.adj_interval
            if self.poll < self.req_poll and self.drift_num > 25:
                if abs(delta_per_sec) < _POLL_INC_AT:
                    self.poll <<= 1
                    self.drift_save()
            elif self.poll > _MIN_POLL:
                if abs(delta_per_sec) > _POLL_DEC_AT:
                    self.poll >>= 1
            if self.debug:
                print("ntpclient: state at", utime.localtime())
                print("ntpclient: delta:", delta,
                      "per_sec:", delta_per_sec)
                print("ntpclient: drift_sum:", self.drift_sum,
                      "num:", self.drift_num, "avg:", avg_drift)
                print("ntpclient: new adj_delta:", self.adj_delta,
                      "new poll:", self.poll)
                print("----")
            self.adj_sum = 0
            self.adj_num = 0

            # Cleanup
            del current, delta, corr, drift, avg_drift

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
