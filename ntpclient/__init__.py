from sys import platform

if platform == 'esp32':
    from .ntpclient_esp32 import *
else:
    raise Exception("unsupported platform '{}'".format(platform))
