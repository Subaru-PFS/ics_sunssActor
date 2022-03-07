import queue
import logging
import time

import astropy.coordinates as coords
import astropy.time as astroTime

subaru = coords.EarthLocation.of_site('Subaru')

def sunIsDown():
    """Is the sun below the horizon?

    Warning: on the 2020-Q1 PFS VMs, this takes ~70ms
    """
    now = astroTime.Time(time.time(), format='unix', scale='utc')
    here = coords.AltAz(obstime=now, location=subaru)
    sunaltaz = coords.get_sun(now).transform_to(here)

    return sunaltaz.alt.value < -2

class SunssStrategy:
    def __init__(self, ra_cmd=None, dec_cmd=None, sunssState='stopped'):
        self.ra_cmd = ra_cmd
        self.dec_cmd = dec_cmd
        self.sunssState = sunssState

    def sunssIsRunning(self):
        return self.sunssState != 'stopped'

    def stopSunss(self):
        """Arrange to stop SPS exposures and SuNSS tracking """

        self.sunssState = 'stopped'
        return 'stop'

    def startSunss(self, newState, doTrack=False):
        """Arrange to start SuNSS tracking and SPS exposures. """

        # Squirrel away where we are pointed. Some strategies can use that.
        self.ra_cmd = newState['ra_cmd']
        self.dec_cmd = newState['dec_cmd']

        self.sunssState = 'tracking' if doTrack else 'running'
        if doTrack:
            return f'track ra={newState.ra_cmd} dec={newState.dec_cmd}'
        else:
            return 'startExposures'

    def update(self, newState):
        raise NotImplementedError("update must be implemented in subclass")

class IdleStrategy(SunssStrategy):
    """Do nothing. """

    def update(self, newState):
        return ''

class UntrackedStrategy(SunssStrategy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update(self, newState):
        """Implement the most trivial observing strategy, which simply observes without tracking.

        Whenever the dome is open and the sun is below the horizon, take SPS exposures.
        """

        if self.sunssIsRunning():
            # Stop SuNSS if we close or switch to alt-az tracking mode.
            if newState['shutter'] != 'OPEN':
                return self.stopSunss()
            if newState['driveMode'] == 'Pointing':
                return self.stopSunss()
            # We do not care if we move on the sky.
        else:
            # Do not start if dome is closed or we are in alt-az mode;
            if newState['shutter'] != 'OPEN':
                return ''
            if newState['driveMode'] == 'Pointing':
                return ''

            # The shutters do get opened during the day.
            if not sunIsDown():
                return ''

            return self.startSunss(newState, doTrack=False)
        return ''

class GuidingStrategy(SunssStrategy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update(self, newState):
        """Implement an observing strategy for programs where we expect to guide

        Whenever we start Guiding, start SuNSS tracking an SPS exposures.
        Whenever we slew or stop tracking the sky, stop both.

        This is a disaster if the fields are short and/or the observer does not guide.
        """

        if self.sunssIsRunning():
            # Stop SuNSS if we close or switch to alt-az tracking
            # mode.  We *ignore* Unknown mode: that seems to be an
            # artifact when switching modes.  We allow switching
            # between Guiding and Tracking, but we need to stop when
            # the commanded position differs from the current position
            # by some fraction of a fiber diameter. A number of
            # instruments (e.g. HSC and FOCAS) do this (switch to
            # Tracking and move locally) a fair amount.
            #
            if newState['shutter'] != 'OPEN':
                return self.stopSunss()
            if newState['driveMode'] in {'Slewing', 'Pointing'}:
                return self.stopSunss()

            return ''

        else:
            # Do not start if dome is closed or we are not now Guiding
            if newState['shutter'] != 'OPEN':
                return ''
            if newState['driveMode'] != 'Guiding':
                return ''

            # The shutters do get opened during the day.
            if not sunIsDown():
                return ''

            return self.startSunss(newState, doTrack=True)

class SunssTracker:
    strategies = dict(untracked=UntrackedStrategy,
                      idle=IdleStrategy,
                      guiding=GuidingStrategy)

    def __init__(self, actor):
        self.actor = actor
        self.in_q = queue.Queue()
        self.logger = logging.getLogger('logic')

        self.resolveStrategy()

    def resolveStrategy(self, name=None):
        """Wire in the named observing strategy. """

        if name is None or name == 'default':
            name = 'untracked'
        try:
            strategy = self.strategies.get(name, None)
        except KeyError:
            raise KeyError(f'unknown observing strategy {name}')

        self.strategy = strategy()
        self.strategyName = name

    def logfileName(self, unit):
        return f'{unit}_{time.strftime("%Y-%m-%d")}.log'

    def takeAction(self, cmd, action):
        with open(self.logfileName('action'), mode='at') as actFile:
            print(cmd, file=actFile)
        self.actor.callCommand(action)

    def logAction(self, msg):
        with open(self.logfileName('all'), mode='at') as logfile:
            logfile.write(msg + '\n')

    def _convertRaDecToDegrees(self, raStr, decStr):
        """Convert RA in H:M:S and Dec in D:M:S to decimal degrees. """

        ra=coords.Angle(raStr, unit='hourangle')
        dec=coords.Angle(decStr, unit='deg')

        return ra.deg, dec.deg

    def convertRawStatus(self, rawStatus):
        """Convert raw gcam status dictionary to something we want."""

        ra_cmd, dec_cmd = self._convertRaDecToDegrees(rawStatus['FITS.SBR.RA_CMD'],
                                                      rawStatus['FITS.SBR.DEC_CMD'])
        ra, dec = self._convertRaDecToDegrees(rawStatus['FITS.SBR.RA'],
                                              rawStatus['FITS.SBR.DEC'])

        # normalize Teldrive name. There can be submodes, as in Guiding(HSC)
        drive = rawStatus['STATL.TELDRIVE']
        paren = drive.find('(')
        if paren >= 0:
            drive = drive[:paren]

        shutter = rawStatus['STATL.DOMESHUTTER_POS']
        alt = rawStatus['FITS.SBR.ALTITUDE']

        d = dict(ra_cmd=ra_cmd, dec_cmd=dec_cmd,
                 ra=ra, dec=dec,
                 ra_offset=rawStatus["STATL.RA_OFFSET"],
                 dec_offset=rawStatus["STATL.DEC_OFFSET"],
                 shutter=shutter, alt=alt, driveMode=drive)
        return d

    def update(self, rawStatus, gcamStatus=None):
        """This is the routine called when new status has come from the gcam world. Which it does at 1 Hz.
        """
        status = self.convertRawStatus(rawStatus)

        try:
            act = self.strategy.update(status)
        except Exception as e:
            act = f'boom: {e}'

        msg = f'{time.strftime("%Y-%m-%dT%H:%M:%S")} ' \
              f'{status["ra_cmd"]:0.6f} {status["dec_cmd"]:0.6f} {status["ra"]:0.6f} {status["dec"]:0.6f} ' \
              f'{status["ra_offset"]} {status["dec_offset"]} {status["shutter"]} ' \
              f'{status["alt"]:0.2f} {status["driveMode"]} {act}'

        self.logAction(msg)
        if act:
            self.takeAction(msg, act)
