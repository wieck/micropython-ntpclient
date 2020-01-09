# ntpclient_esp8266.py

import os
import usocket as socket
import ustruct as struct
from machine import RTC, Pin
import uasyncio as asyncio
import utime
import gc

from .ntpclient_base import *

# ntpclient -
#   Class implementing the uasyncio based NTP client
class ntpclient(ntpclient_base):
    def __init__(self, **base_args):
        self.cal_value = 0
        self.cal_todo = 0

        ntpclient_base.__init__(self, **base_args)

    async def _poll_task(self):
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
                                r[4], r[5], r[6], 0, 0)), r[7] * 1000)
        rtc_diff_us = time_diff_us(ts_now, ts_rtc)
        if abs(rtc_diff_us) > self.max_startup_delta:
            now = utime.localtime(ts_now[0])
            if self.debug:
                print("ntpclient: RTC delta too large, setting rtc to", now)
            self.rtc.datetime((now[0], now[1], now[2], now[6],
                               now[3], now[4], now[5], ts_now[1] // 1000))

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

            self.cal_todo = delta // 100
            if abs(self.cal_todo // self.poll) > 6:
                self.cal_value = self.cal_todo // self.poll
                if self.cal_value > 200:
                    self.cal_value = 200
                elif self.cal_value < -200:
                    elf.cal_value = -200
            else:
                if self.cal_todo == 0:
                    self.cal_value = 0
                elif self.cal_todo > 6:
                    self.cal_value = 6
                elif self.cal_todo < -6:
                    self.cal_value = -6
                else:
                    self.cal_value = self.cal_todo

            if self.poll < MAX_POLL and self.cal_value < 10:
                self.poll <<= 1
            elif self.poll > MIN_POLL and self.cal_value > 27:
                self.poll >>= 1

            if self.debug:
                print("ntpclient: delta:", delta, "rondtrip:", current[0])
                print("ntpclient: cal_value:", self.cal_value,
                      "cal_todo:", self.cal_todo,
                      "poll:", self.poll)
                print("----")

    async def _adj_task(self):
        # This task slimply calls calibrate() every _CAL_INTERVAL seconds
        # to have the RTC calibration and delta recalculated and the
        # current offset added.
        while True:
            await asyncio.sleep(ADJ_INTERVAL)
            self.rtc.calibrate(self.cal_value)
            self.cal_todo -= self.cal_value
            if abs(self.cal_value) > abs(self.cal_todo):
                self.cal_value = self.cal_todo
                print("cal_value:", self.cal_value, "cal_todo:", self.cal_todo)

