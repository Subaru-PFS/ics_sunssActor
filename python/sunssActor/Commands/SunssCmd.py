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
            ('sunss', '@raw', self.sunssRaw),
            ('status', '', self.status),
            ('stop', '', self.stop),
            ('track', '<ra> <dec> [<speed>]', self.track),
            ('startExposures', '', self.startExposures),
            ('reloadTracker', '', self.reloadTracker),
        ]
        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("sunss", (1, 1),
                                        keys.Key("ra", types.Float(),
                                                 help='RA degrees to start tracking from'),
                                        keys.Key("dec", types.Float(),
                                                 help='Dec degrees to start tracking from'),
                                        keys.Key("speed", types.Int(), default=1,
                                                 help='Tracking speed multiple to test with'),
                                        )

        self.state = None

    @property
    def pi(self):
        return self.actor.controllers['sunss_pi']

    def sunssRaw(self, cmd):
        """ Send a raw command to the temps controller. """

        cmd_txt = cmd.cmd.keywords['raw'].values[0]

        ret = self.pi.sunssCmd(cmd_txt, cmd=cmd)
        cmd.finish('text=%s' % (qstr('returned: %s' % (ret))))

    def reloadTracker(self, cmd):
        """ Reload the SuNSS tracking logic module """

        reload(sunssTracker)
        newTracker = sunssTracker.SunssTracker()
        self.actor.tracker = newTracker

        cmd.finish()

    def startExposures(self, cmd):
        """ Start SPS exposures, without starting tracking. """

        cmd.fail('text="Not implemented yet"')

    def status(self, cmd, doFinish=True):
        """ Report status keys. """

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

        cmd.finish('sunssRunning=%d,%d,%d,%d' % (tracking, moving, stepTs, steps))

    def _getSunssSm(self, cmd):
        """Figure out which SM, if any, is connectedb to SuNSS. """

        iicModel = self.actor.models['iic'].keyVarDict
        sm = None
        for i in range(1,5):
            ls =  iicModel[f'sm{i}lightSource'].values[0]
            if ls == 'sunss':
                sm = f'sm{i}'
                break
        self.logger.inform(f'found SuNSS on SM {sm}')

        return sm

    def iicStatus(self, cmd):
        """Figure out what iic can or is doing on our behalf. """

        sunssSm = self._getSunssSm(cmd)
        if sunssSm is None:
            return None, None

    def iccStart(self, cmd, exptime=1200.0):
        """Start a new SPS exposure if we can."""

        pass

    def stop(self, cmd):
        """ Stop any current move and exposure. """

        ret = self.pi.sunssCmd('stop', cmd=cmd)
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
        speed = 1 if 'speed' not in cmdKeys else cmdKeys['speed'].values[0]
        ha, time0 = self._raToHa(ra)

        cmd.inform(f'text="track ra,dec={ra},{dec} to ha,dec,time={ha},{dec},{time0}"')
        ret = self.pi.sunssCmd(f'track {ha} {dec} {time0} {speed}', cmd=cmd)
        self.status(cmd)
