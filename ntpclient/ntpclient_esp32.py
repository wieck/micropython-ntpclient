# ntpclient.py

import os
import usocket as socket
import ustruct as struct
from machine import RTC, Pin
import uasyncio as asyncio
import utime
import gc

from .ntpclient_base import *

# Poll increment/decrement water marks
_POLL_INC_AT = 50       # increase interval when the delta per second
                        # falls below this number of microseconds
_POLL_DEC_AT = 200      # decrease interval when the delta per second
                        # grows above this number

# Drift file configuration
_DRIFT_FILE_VERSION = 1
_DRIFT_NUM_MAX = 200    # Aggregate when we have this many samples
_DRIFT_NUM_AVG = 100    # Aggregate down to this many and save drift file

# ntpclient -
#   Class implementing the uasyncio based NTP client
class ntpclient(ntpclient_base):
    def __init__(self, drift_file = None, **base_args):
        self.drift_file = drift_file
        self.last_delta = None
        self.drift_sum = 0
        self.drift_num = 0
        self.adj_delta = 0
        self.adj_sum = 0
        self.adj_num = 0

        ntpclient_base.__init__(self, **base_args)

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
                self.poll = MIN_POLL
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
            # per ADJ_INTERVAL is below or above a certain threshold.
            # This means we poll less if we think we are close to
            # the server and more often while homing in.
            delta_per_sec = delta // self.adj_num // ADJ_INTERVAL
            if self.poll < self.req_poll and self.drift_num > 25:
                if abs(delta_per_sec) < _POLL_INC_AT:
                    self.poll <<= 1
                    self.drift_save()
            elif self.poll > MIN_POLL:
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
        # This task slimply calls adjtime() every ADJ_INTERVAL seconds
        # and sums up how much of a total slew it produced in how many
        # calls. The poll_task will use this feedback data in calculating
        # the new delay.
        while True:
            await asyncio.sleep(ADJ_INTERVAL)
            if self.adj_delta != 0:
                delta = self.adj_delta
                utime.adjtime((0, delta))
                self.adj_sum += delta
                del delta
            self.adj_num += 1
