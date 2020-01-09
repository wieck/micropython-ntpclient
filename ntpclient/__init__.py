from sys import platform

if platform == 'esp32':
    from .ntpclient_esp32 import *
elif platform == 'esp8266':
    from .ntpclient_esp8266 import *
else:
    raise Exception("unsupported platform '{}'".format(platform))
