#!/usr/bin/env python

from importlib import reload
import numpy as np

import time

import astropy
from astropy import units as u
from astropy.coordinates import SkyCoord

import opscore.protocols.keys as keys
import opscore.protocols.types as types
from opscore.utility.qstr import qstr

from ics.sunssActor import sunssTracker
reload(sunssTracker)

class SunssCmd(object):

    def __init__(self, actor):
        # This lets us access the rest of the actor.
        self.actor = actor

        # Declare the commands we implement. When the actor is started
        # these are registered with the parser, which will call the
        # associated methods when matched. The callbacks will be
        # passed a single argument, the parsed and typed command.
        #
        self.vocab = [
            ('pi', '@raw', self.sunssRaw),
            ('pi', 'move <degrees>', self.move),
            ('pi', 'move <steps>', self.move),
            ('status', '', self.status),
            ('stop', '', self.stop),
            ('track', '<ra> <dec> [@noExp] [<speed>] [<exptime>]', self.track),
            ('enable', '[<strategy>]', self.enable),
            ('disable', '', self.disable),
            ('startExposures', '', self.startExposures),
            ('takeFlats', '', self.takeFlats),
            ('reloadTracker', '', self.reloadTracker),
        ]
        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("sunss", (1, 1),
                                        keys.Key("ra", types.Float(),
                                                 help='RA degrees to start tracking from'),
                                        keys.Key("dec", types.Float(),
                                                 help='Dec degrees to start tracking from'),
                                        keys.Key("exptime", types.Float(),
                                                 help='Exposure time'),
                                        keys.Key("degrees", types.Float(),
                                                 help='Degrees to move frm current position'),
                                        keys.Key("steps", types.Int(),
                                                 help='Steps to move frm current position'),
                                        keys.Key("speed", types.Int(), default=1,
                                                 help='Tracking speed multiple to test with'),
                                        keys.Key("strategy", types.String(),
                                                 help='How to respond to telescope changes'),
                                        )

        self.state = 'stopped'
        self.connected = False

    @property
    def pi(self):
        return self.actor.controllers['sunss_pi']

    def sunssRaw(self, cmd):
        """ Send a raw command to the temps controller. """

        cmd_txt = cmd.cmd.keywords['raw'].values[0]

        ret = self.pi.sunssCmd(cmd_txt, cmd=cmd)
        cmd.finish('text=%s' % (qstr('returned: %s' % (ret))))

    def move(self, cmd):
        """ Rotate SuNSS imager by steps or degrees """

        cmdKeys = cmd.cmd.keywords
        if 'steps' in cmdKeys:
            steps = cmdKeys['steps'].values[0]
        elif 'degrees' in cmdKeys:
            degrees = cmdKeys['degrees'].values[0]
            steps = degrees*8.88889

        ret = self.pi.sunssCmd(f'runit {int(steps)}', timelim=10.0, cmd=cmd)
        self.status(cmd)

    def reloadTracker(self, cmd):
        """ Reload the SuNSS tracking logic module """

        reload(sunssTracker)
        newTracker = sunssTracker.SunssTracker(self.actor)
        self.actor.tracker = newTracker

        cmd.finish()

    def status(self, cmd, doFinish=True):
        """ Report status keys. """

        if not self.connected:
            self.actor.sendVersionKey(cmd)
            self.connected = True

        ret = self.pi.sunssCmd('status', cmd=cmd)
        ret = ret.split()
        try:
            tracking = int(ret[0])
            stepTs = int(ret[1])
            steps = int(ret[2])
            moving = int(ret[3])
        except Exception as e:
            cmd.warn(f'text="failed to get or parse sunss status: {ret}"')
            tracking = 0
            stepTs = 0
            steps = -1
            moving = 0

        cmd.inform(f'sunssState={self.state}; sunssStrategy={self.actor.tracker.strategyName}')
        cmd.finish('sunssRunning=%d,%d,%d,%d' % (tracking, moving, stepTs, steps))

    def _getSunssSm(self, cmd):
        """Figure out which SM, if any, is connectedb to SuNSS. """

        spsModel = self.actor.models['sps'].keyVarDict
        sm = None
        for i in range(1,5):
            ls =  spsModel[f'sm{i}LightSource'].valueList[0]
            if ls == 'sunss':
                sm = i
                break
        self.actor.logger.info(f'found SuNSS on SM {sm}')

        return sm

    def startExposures(self, cmd, tracking=False, doFinish=True, exptime=1200.0):
        """ Start SPS exposures, without starting tracking. """

        sm = self._getSunssSm(cmd)
        if sm is None:
            cmd.fail('text="SuNSS is not connected to a SM"')
            return

        if self.state == 'integrating':
            cmd.fail('text="SPS is already integrating"')
            return

        name = f'sunss_{"tracking" if tracking else "untracked"}'

        # Temporarily (until INSTRM-xxxx changes startExposures to return after validation
        # and resource allocation), make command timeout quickly and ignore timeLim failures.
        ret = self.actor.safeCall(cmd, 'iic',
                                  f'sps startExposures exptime={exptime} sm={sm} name={name}',
                                  timeLim=5)
        if ret.didFail:
            if 'Timeout' not in ret.replyList[-1].keywords:
                raise RuntimeError(f'failed to start sps exposures: {ret}')

        self.state = 'integrating'
        self.status(cmd, doFinish=doFinish)

    def takeFlats(self, cmd):
        """ Start a set of SuNSS flats. """

        cmd.fail('text="Not implemented yet"')

    def enable(self, cmd):
        """ Enable logic on Gen2 keywords """

        cmdKeys = cmd.cmd.keywords
        strategy = cmdKeys['strategy'].values[0] if 'strategy' in cmdKeys else 'default'

        self.actor.tracker.resolveStrategy(strategy)
        self.status(cmd)

    def disable(self, cmd):
        """ Disable any actions based on Gen2 keywords. """

        self.actor.tracker.resolveStrategy('idle')
        self.status(cmd)

    def stop(self, cmd):
        """ Stop any current move and exposure. """

        if self.state != 'stopped':
            ret = self.actor.safeCall(cmd, 'iic',
                                      f'sps finishExposure',
                                      timeLim=5)
        if self.state is 'tracking':
            ret = self.pi.sunssCmd('stop', timelim=6.0, cmd=cmd)

        self.state = 'stopped'
        self.status(cmd)

    def _now(self):
        """ Return an astropy.time.Time for now. """

        return astropy.time.Time(time.time(), format='unix', scale='utc')

    def _raToHa(self, ra):
        now = self._now()
        location = astropy.coordinates.EarthLocation.of_site('Subaru')
        lst = now.sidereal_time('apparent', location.lon)

        ha = lst.deg - ra
        return ha, now.unix

    def track(self, cmd):
        """ Start tracking from a given sky position. """

        cmdKeys = cmd.cmd.keywords
        ra = cmdKeys['ra'].values[0]
        dec = cmdKeys['dec'].values[0]
        dec = cmdKeys['dec'].values[0]
        noExp = 'noExp' in cmdKeys
        speed = 1 if 'speed' not in cmdKeys else cmdKeys['speed'].values[0]
        exptime = 1200.0 if 'exptime' not in cmdKeys else cmdKeys['exptime'].values[0]
        ha, time0 = self._raToHa(ra)

        cmd.inform(f'text="track ra,dec={ra},{dec} to ha,dec,time={ha},{dec},{time0}"')
        ret = self.pi.sunssCmd(f'track {ha} {dec} {time0} {speed}', timelim=15, cmd=cmd)

        if not noExp:
            self.startExposures(cmd, tracking=True, exptime=exptime)
        self.state = 'tracking'
