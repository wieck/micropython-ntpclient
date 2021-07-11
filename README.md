micropython-ntpclient
=====================

A uasyncio based NTP client for ESP32/ESP8266 boards running micropython.

**At this moment this code only works on boards with a custom build
micropython firmware.**

Please go to https://forum.micropython.org/viewtopic.php?f=15&t=7567
for discussion and questions. 

**The following commits were never accepted by the upstream project.
In order to make the utime.adjtime() available please apply the
included patch _esp32_adjtime.diff_ and build a custom micropython image.**

~~Required commit to be cherry-picked for ESP32: 
https://github.com/wieck/micropython/commit/cd80a9aba99a68af7e295067fa7d35383ccef640~~

~~Required commit to be cherry-picked for ESP8266: 
https://github.com/wieck/micropython/commit/97e58630e74b024b58aeb5964d104973b361cad5~~


Installation and testing
------------------------

The ntpclient module requires the above commit(s) to be cherry-picked
into a custom build of micropython. For the ESP32 it adds the utime.adjtime()
function that uses the adjtime(3) function of the ESP32 SDK.

Once your board is flashed with that custom build, upload the
ntpclient directory and ntpclient_test[12].py scripts. You also need to upload
a ```boot.py``` that enables WiFi and connects to your WLAN.

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
import ntpclient_test2
ntpclient_test2.run(pps = 17, host = 'my.local.ntp.host.addr', scl = 22, sda = 21, debug=True)
```

Congratulations, you now have an NTP based clock that displays UTC.

Syntax
------

```
ntpclient.ntpclient(**kwargs)

kwargs:
  
  host=HOSTNAME     Hostname of the NTP server to use (default pool.ntp.org).

  poll=SECONDS      Maximum poll interval (default 1024). ntpclient will
                    dynamically increase/decrease the polling interval based
                    on current instability between 64 and this maximum
                    number of seconds.
  
  max_startup_delta=SECONDS
                    Number of seconds of clock difference at which
                    ntpclient will perform a hard set of the clock on
                    startup instead of slewing the clock (default 1).

  debug=BOOL        Flag to make ntpclient emit debug messages on stdout
                    for diagnostics.
```

Example
-------
```
include ntpclient
ntpclient.ntpclient(host = 'ntpserver.localdomain')
```

Saving Drift information
------------------------

On the ESP32 port an optional keyword argument to the ntpclient instance is
the path for a "drift_file". In this file ntpclient will periodically
save drift information to speed up synchronization on subsequent
reboots.


Implementation Notes
--------------------

* On the ESP32 the RTC is running on the main XTAL while under full power.
  The algorithm tries to calculate the current "drift" of that oscillator.
  From this drift, measured in microseconds per adjustment interval, it
  calculates a number of microseconds by which to "slew" the RTC every
  two seconds using the new adjtime() function. This is basically a
  simplified version of what ntpd does on a Unix system.
