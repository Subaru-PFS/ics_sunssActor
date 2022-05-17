"""
Example to stream status items from Gen2

IMPORTANT:

[1] If you need only a limited number of status items and you don't need
updates any faster than 10 sec interval, please consider using the
StatusClient() class--(see the "fetch_status.py" example).

[2] The StatusStream class gives you a roughly 1Hz stream of updated
status items from Gen2.  It does not give you ALL status items in each
update--ONLY the items that have CHANGED since the last update.  You
may need therefore to use the StatusClient class to fetch your initial
values for status items, as shown in the example below.

[3] Do not rely on the internals of the StatusStream class!!!
The implementation details are subject to change suddenly!

"""
import sys
import argparse
import threading
import time
import queue as Queue

import astropy.coordinates as coords

from g2cam.status.client import StatusClient
from g2cam.status.stream import StatusStream

class SunssTracker:
    def __init__(self):
        self.ra = None
        self.deg = None
        self.shutter = None
        self.drive = None
        self.state = 'unknown'

    def logfileName(self, unit):
        return f'{unit}_{time.strftime("%Y-%m-%d")}.log'

    def takeAction(self, cmd):
        with open(self.logfileName('action'), mode='at') as actFile:
            actFile.write(cmd + '\n')

    def logAction(self, msg):
        with open(self.logfileName('all'), mode='at') as logfile:
            logfile.write(msg + '\n')

    def trackDrive(self):
        ret = ''
        if self.state in ('unknown', 'Pointing'):
            # Starting to move.
            if self.drive == 'Slewing':
                self.state = 'Slewing'
        elif self.state == 'Slewing':
            # Going to new field
            if self.drive != 'Slewing':
                self.state = self.drive
        elif self.state == 'Tracking':
            # Starting new stable field
            if self.drive != 'Guiding':
                self.state = 'onfield'
                self.fieldRa = self.ra
                self.fieldDec =  self.dec
                ret = f'track {self.ra} {self.dec}'
        elif self.state == 'onfield':
            # On active SuNSS field. Allow us to toggle between Tracking and Guiding
            if self.drive not in ('Guiding', 'Tracking'):
                self.state = self.drive
                ret = 'stop'

        return ret

    def _convertRaDecToDegrees(self, raStr, decStr):
        here = coords.FK5(ra=coords.Angle(raStr, unit='hourangle'),
                          dec=coords.Angle(decStr, unit='deg'))
        return here.ra.deg, here.dec.deg

    def lamps(self, status):
        lampNames = ('STATL.LAMP',)

        return ",".join([status[name] for name in lampNames])

    def update(self, status):
        raPointing, decPointing = self._convertRaDecToDegrees(status['FITS.SBR.RA_CMD'],
                                                              status['FITS.SBR.DEC_CMD'])
        ra, dec = self._convertRaDecToDegrees(status['FITS.SBR.RA'],
                                              status['FITS.SBR.DEC'])

        # normalize Teldrive name. Guiding(HSC)
        drive = status['STATL.TELDRIVE']
        paren = drive.find('(')
        if paren >= 0:
            drive = drive[:paren]

        shutter = status['STATL.DOMESHUTTER_POS']
        alt = status['FITS.SBR.ALTITUDE']

        self.ra = ra
        self.dec = dec
        self.shutter = shutter
        self.drive = drive

        try:
            act = self.trackDrive()
        except Exception as e:
            act = f'boom: {e}'

        msg = f'{time.strftime("%Y-%m-%dT%H:%M:%S")} ' \
              f'{raPointing:0.6f} {decPointing:0.6f} {ra:0.6f} {dec:0.6f} ' \
              f'{status["STATL.RA_OFFSET"]} {status["STATL.RA_OFFSET"]} {shutter} ' \
              f'{alt:0.2f} {drive} {self.lamps(status)} {act}'

        self.logAction(msg)
        if act:
            self.takeAction(msg)

def main(options, args):
    # setup (use the Gen2 host, user name and password you are advised by
    # observatory personnel)
    sc = StatusClient(host=options.host, username=options.username,
                      password=options.password)
    sc.connect()

    # fetch a dictionary
    d = {'FITS.SBR.RA_CMD': None,
         'FITS.SBR.DEC_CMD': None,
         'FITS.SBR.RA': None,
         'FITS.SBR.DEC': None,
         'STATL.RA_OFFSET': None,
         'STATL_DEC_OFFSET': None,
         'FITS.SBR.ALTITUDE': None,
         'STATL.TELDRIVE': None,
         'STATL.DOMESHUTTER_POS': None,
         'STATL.LAMP': None,
         'TSCV.DomeFF_A': None,
         'TSCV.DomeFF_1B': None,
         'STATL.CAL.HAL.LAMP1': None,
    }
    sc.fetch(d)

    ss = StatusStream(host=options.streamhost, username=options.stream_username,
                      password=options.stream_password)
    ss.connect()

    # create a queue to receive the status updates
    status_q = Queue.Queue()
    # shared event to signal termination of processing
    ev_quit = threading.Event()

    # start a thread to put status updates on the queue
    t = threading.Thread(target=ss.subscribe_loop, args=[ev_quit, status_q])
    t.start()

    tracker = SunssTracker()

    # consume items from queue
    try:
        print("consuming on queue...")
        while not ev_quit.is_set():
            envelope = status_q.get()
            changed = envelope['status']
            d.update({k: changed[k] for k in d if k in changed})
            tracker.update(d)

    except KeyboardInterrupt as e:
        ev_quit.set()


if __name__ == '__main__':

    # Parse command line options
    argprs = argparse.ArgumentParser()

    argprs.add_argument("--streamhost", dest="streamhost", metavar="HOST",
                        default='localhost',
                        help="Fetch streaming status from HOST")
    argprs.add_argument("--streamuser", dest="stream_username", default="none",
                        metavar="USERNAME",
                        help="Authenticate using USERNAME")
    argprs.add_argument("-sp", "--streampass", dest="stream_password",
                        default="none",
                        metavar="PASSWORD",
                        help="Authenticate for streams using PASSWORD")
    argprs.add_argument("--host", dest="host", metavar="HOST",
                        default='localhost',
                        help="Fetch status from HOST")
    argprs.add_argument("--user", dest="username", default="none",
                        metavar="USERNAME",
                        help="Authenticate using USERNAME")
    argprs.add_argument("-p", "--pass", dest="password", default="none",
                        metavar="PASSWORD",
                        help="Authenticate using PASSWORD")
    (options, args) = argprs.parse_known_args(sys.argv[1:])

    if len(args) != 0:
        argprs.error("incorrect number of arguments")

    main(options, args)
