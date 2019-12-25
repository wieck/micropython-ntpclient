from machine import I2C, Pin, RTC
import uasyncio as asyncio
import utime
import ssd1306

import ntpclient

i2c = I2C(-1, scl=Pin(22), sda=Pin(21))
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

async def test2_square(pin):
    global oled

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
        oled.fill(0)
        now = utime.localtime()
        oled.text("{0:04d}-{1:02d}-{2:02d}".format(*now), 0, 0)
        oled.text("  {3:02d}:{4:02d}:{5:02d}".format(*now), 0, 8)
        oled.show()

        # Wait for 100ms
        delay = (100000 - rtc.datetime()[7]) // 1000
        if delay > 0:
            await asyncio.sleep_ms(delay)

        # Turn the pin off
        pin.value(0)

def run(pps_pin = 17, **kwarg):
    pin = Pin(pps_pin, mode=Pin.OUT)
    client = ntpclient.ntpclient(**kwarg)
    asyncio.create_task(test2_square(pin))
    asyncio.run_until_complete()

