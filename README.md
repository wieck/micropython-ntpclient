micropython-ntpclient
=====================

A uasyncio based NTP client for ESP32 boards running micropython.

**This is a proof of concept. Do not use in production at this point!**

**At this moment this code only works on ESP32 based boards with a
custom build and the new uasyncio module!**

Please go to https://forum.micropython.org/viewtopic.php?f=18&t=7403
for discussion and questions. 

Required commit to be cherry-picked: 
https://github.com/wieck/micropython/commit/cd80a9aba99a68af7e295067fa7d35383ccef640

Required uasyncio:
https://github.com/dpgeorge/micropython/blob/extmod-uasyncio/extmod/uasyncio.py


Installation and testing
------------------------

The ntpclient module requires the above commit to be cherry-picked
into a custom build of micropython. This adds the utime.adjtime() function
that uses the adjtime(3) function of the ESP32 SDK.

Once your ESP32 board is flashed with that custom build, upload the
ntpclient.py and ntpclient_test1.py scripts. You also need to upload
a ```boot.py``` that enables WiFi and connects to your WLAN as well as
the new uasyncio.

Then use a REPL prompt and
```
import ntpclient_test1
ntpclient_test1.run(pps_pin = 17, host = 'my.local.ntp.host.addr', debug=True)
```

Replace "my.local.ntp.host.addr" with your local NTP server. If you don't have
one, you can omit the whole "host=" kwarg and it will default to
"pool.ntp.org". But be warned, those have unpredictably asynchronous
delays in packet travel, which isn't very well tested at this moment.

The above will run a uasyncio task that prints the current time every
second as well as producing a 100ms pulse on the specified "pps_pin".
The ntpclient will be running in the background, constantly adjusting
the ESP32's RTC. The ntpclient will occasionally output debug info like

```
ntpclient: state at (2019, 12, 25, 4, 44, 18, 2, 359)
ntpclient: deltas: [-533, -520, -701, -573, -630] delta: 401
ntpclient: corr: 410 drift: -1 drift_hist: [0, -1, -1]
ntpclient: avg_drift: -1 new adj_delta: -1
ntpclient: adj_hist: [0, -2, -1] new poll: 1024
```

The above tells us that the current average delta (time offset) between
the NTP server and the ESP32 is 401us. During the last adjustment round
that delta changed by 410us (corr). The RTC of the module is estimated
to drift by -1us every 2ms (which is the not yet
explained adjustment interval). Anyhow, as said, this isn't ready for
prod ... the next NTP server poll will happen in 1024 seconds, which is
about 17 minutes. Initially it will start polling every 64 seconds and
only get to longer intervals if it becomes stable.

With nothing else running on the ESP32, you now have a clock that will
most likely tell you the correct UTC time with only a few milliseconds
of error.
