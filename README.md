micropython-ntpclient
=====================

A uasyncio based NTP client for ESP32/ESP8266 boards running micropython.

**This is a proof of concept. Do not use in production at this point!**

**At this moment this code only works on boards with a
custom build and the new uasyncio module!**

Please go to https://forum.micropython.org/viewtopic.php?f=15&t=7567
for discussion and questions. 

Required commit to be cherry-picked for ESP32: 
https://github.com/wieck/micropython/commit/cd80a9aba99a68af7e295067fa7d35383ccef640

Required commit to be cherry-picked for ESP8266: 
https://github.com/wieck/micropython/commit/97e58630e74b024b58aeb5964d104973b361cad5

Required uasyncio:
https://github.com/dpgeorge/micropython/blob/extmod-uasyncio/extmod/uasyncio.py


Installation and testing
------------------------

The ntpclient module requires the above commit(s) to be cherry-picked
into a custom build of micropython. For the ESP32 it adds the utime.adjtime()
function that uses the adjtime(3) function of the ESP32 SDK.

Once your board is flashed with that custom build, upload the
ntpclient directory and ntpclient_test[12].py scripts. You also need to upload
a ```boot.py``` that enables WiFi and connects to your WLAN as well as
the new uasyncio.

Then use a REPL prompt and
```
import ntpclient_test1
ntpclient_test1.run(pps = 17, host = 'my.local.ntp.host.addr', debug=True)
```

Replace "my.local.ntp.host.addr" with your local NTP server. If you don't have
one, you can omit the whole "host=" kwarg and it will default to
"pool.ntp.org". But be warned, those have unpredictably asynchronous
delays in packet travel.

The above will run a uasyncio task that prints the current time every
second as well as producing a 100ms pulse on the specified "pps" pin.
The ntpclient will be running in the background, constantly adjusting
the boards RTC.

Please note that attempting to slew a RTC while using deep sleep is
not going to work. The ntpclient needs to adjust or calibrate the RTC
every 2 seconds in order to be considered "in sync".

If you have an SSD1306 OLED display you can also use ntpclient_test2.
```
import ntpclient_test1
ntpclient_test1.run(pps = 17, host = 'my.local.ntp.host.addr', scl = 22, sda = 21, debug=True)
```

Congratulations, you now have an NTP based clock that displays UTC.


Implementation Notes
--------------------

The mechanism to adjust the RTC is very different for each platform.

* On the ESP32 the RTC is running on the main XTAL while under full power.
  The algorithm tries to calculate the current "drift" of that oscillator.
  From this drift, measured in microseconds per adjustment interval, it
  calculates a number of microseconds by which to "slew" the RTC every
  two seconds using the new adjtime() function. This is basically a
  simplified version of what ntpd does on a Unix system.

* On the ESP8266 the RTC is running on an internal 150kHz oscillator.
  This oscillator has some severe jitter and changes its speed by up to
  +/- 5%, mostly caused by temperature changes. The above commit adds a
  function machine.RTC.calibrate() which uses system_rtc_clock_cali_proc()
  to recalibrate the clock based on the current main XTAL. It also
  takes an optional argument by which the calibration value can be offset
  in order to slew the clock. The function also adjusts the internal
  "delta" value, that all time based functions use to calculate the
  actual time since epoch.

Both implementations make the RTC appear monotonic and keep it more or
less in sync. Because the ESP8266 is not using a crystal based RTC, it
will wander off between server polls by up to 50ms even when using a
local NTP server (yes, that much). By default those server polls
will eventually happen only every 17 minutes, once the system has
settled in. The ntpclient class does take an optional "poll" argument,
that lets you override the maximum poll interval, but please only use
that if you also provide a local "host" as your NTP server. 'pool.ntp.org'
are public servers that other people pay for. Squandering those
resources because your microcontroller has a bad RTC implementation is
not fair.
