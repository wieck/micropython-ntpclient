from machine import RTC, Pin
import uasyncio as asyncio
import utime

import ntpclient

async def test1_square(pin):
    rtc = RTC()
    while True:
        # We want maximum precision, so we let await get us within 2ms,
        # then use a blocking utime.sleep_us() to strike. Every now and
        # the something will interfere ... meh.
        delay = (1000000 - rtc.datetime()[7]) // 1000
        if delay > 4:
            await asyncio.sleep_ms(delay - 2)
        delay = (1000000 - rtc.datetime()[7])
        if delay > 0:
            utime.sleep_us(delay)

        # Turn the pin on and print the current time on REPL
        pin.value(1)
        now = utime.localtime()
        print("{0:04d}-{1:02d}-{2:02d} {3:02d}:{4:02d}:{5:02d}".format(*now))

        # Wait for 100ms
        delay = (100000 - rtc.datetime()[7]) // 1000
        if delay > 0:
            await asyncio.sleep_ms(delay)

        # Turn the pin off
        pin.value(0)

def run(pps_pin = 17, **kwargs):
    pin = Pin(pps_pin, mode = Pin.OUT)
    client = ntpclient.ntpclient(**kwargs)
    asyncio.create_task(test1_square(pin))
    asyncio.run_until_complete()

