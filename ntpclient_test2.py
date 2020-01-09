import sys
from machine import I2C, Pin, RTC
import uasyncio as asyncio
import utime
import ssd1306

import ntpclient

async def test2_square(pin, scl, sda):
    i2c = I2C(-1, scl=scl, sda=sda)
    oled = ssd1306.SSD1306_I2C(128, 64, i2c)
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
        oled.fill(0)
        now = utime.localtime()
        oled.text("{0:04d}-{1:02d}-{2:02d}".format(*now), 0, 0)
        oled.text("  {3:02d}:{4:02d}:{5:02d}".format(*now), 0, 8)
        oled.show()

        # Wait for 100ms
        if sys.platform == 'esp32':
            delay = (100000 - rtc.datetime()[7]) // 1000
        elif sys.platform == 'esp8266':
            delay = (100 - rtc.datetime()[7])
        if delay > 0:
            await asyncio.sleep_ms(delay)

        # Turn the pin off
        pin.value(0)

def run(pps = None, scl = None, sda = None, **kwarg):
    pps_pin = Pin(pps, mode=Pin.OUT)
    scl_pin = Pin(scl)
    sda_pin = Pin(sda)
    client = ntpclient.ntpclient(**kwarg)
    asyncio.create_task(test2_square(pps_pin, scl_pin, sda_pin))
    asyncio.run_until_complete()
