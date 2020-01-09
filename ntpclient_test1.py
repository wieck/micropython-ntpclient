import sys
from machine import RTC, Pin
import uasyncio as asyncio
import utime

import ntpclient

async def test1_square(pin):
    rtc = RTC()
    while True:
        if sys.platform == 'esp32':
            # We want maximum precision, so we let await get us within 2ms,
            # then use a blocking utime.sleep_us() to strike. Every now and
            # the something will interfere ... meh.
            delay = (1000000 - rtc.datetime()[7]) // 1000
            if delay > 4:
                await asyncio.sleep_ms(delay - 2)
            delay = (1000000 - rtc.datetime()[7])
            if delay > 0:
                utime.sleep_us(delay)
        elif sys.platform == 'esp8266':
            # ESP8266 only has milliseconds, so no point in the above.
            delay = (1000 - rtc.datetime()[7])
            if delay > 0:
                await asyncio.sleep_ms(delay)
        else:
            raise RuntimeError("unsupported platform '{}'".format(sys.platform))

        # Turn the pin on and print the current time on REPL
        pin.value(1)
        now = utime.localtime()
        print("{0:04d}-{1:02d}-{2:02d} {3:02d}:{4:02d}:{5:02d}".format(*now))

        # Wait for 100ms
        if sys.platform == 'esp32':
            delay = (100000 - rtc.datetime()[7]) // 1000
        elif sys.platform == 'esp8266':
            delay = (100 - rtc.datetime()[7])
        if delay > 0:
            await asyncio.sleep_ms(delay)

        # Turn the pin off
        pin.value(0)

def run(pps = None, **kwargs):
    pps_pin = Pin(pps, mode = Pin.OUT)
    client = ntpclient.ntpclient(**kwargs)
    asyncio.create_task(test1_square(pps_pin))
    asyncio.run_until_complete()

