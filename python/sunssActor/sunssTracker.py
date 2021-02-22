import queue
import time

import astropy.coordinates as coords

class SunssTracker:
    def __init__(self):
        self.in_q = queue.Queue()

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
