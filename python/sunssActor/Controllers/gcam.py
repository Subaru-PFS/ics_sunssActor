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

from importlib import reload
import sys
import time
import argparse
import threading
import time
import queue
import logging

import astropy.coordinates as coords

from g2cam.status.client import StatusClient
from g2cam.status.stream import StatusStream

from ics.sunssActor import sunssTracker

reload(sunssTracker)

class gcam(object):
    def __init__(self, actor, name,
                 loglevel=logging.DEBUG):

        self.name = name
        self.actor = actor
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(loglevel)

        self.kwlog = open(self._logname('/data/logs/gen2/kw'), 'w+t')
        self.connect()

    def __del__(self):
        self.logger.warn(f'text="del thread_count={threading.active_count()}"')
        self.quitEvent.set()

    def start(self, cmd=None):
        if cmd is not None:
            cmd.warn(f'text="start thread_count={threading.active_count()}"')

    def stop(self, cmd=None):
        if cmd is not None:
            cmd.warn(f'text="stopping thread_count={threading.active_count()}"')
        self.quitEvent.set()
        time.sleep(1)
        if cmd is not None:
            cmd.warn(f'text="stopped thread_count={threading.active_count()}"')

    def _convertRaDecToDegrees(self, raStr, decStr):
        here = coords.FK5(ra=coords.Angle(raStr, unit='hourangle'),
                          dec=coords.Angle(decStr, unit='deg'))
        return here.ra.deg, here.dec.deg

    def _logname(self, name):
        return time.strftime(f'{name}_%Y-%m-%dT%H:%M:%S.log')

    def _ts(self):
        now = time.time()
        tup = time.localtime(now)
        return time.strftime(f'%Y-%m-%dT%H:%M:%S.{int((now - int(now))*10000):04d}', tup)

    def listener(self, quitEvent=None, gcamQueue=None):
        """The routine which should read from the queue which the g2can streamer is feeding.
        """
        # consume items from queue
        try:
            print("consuming on queue...")
            while not quitEvent.is_set():
                try:
                    envelope = gcamQueue.get(timeout=0.5)
                except queue.Empty:
                    continue
                changed = envelope['status']
                try:
                    kwdict = changed.copy()
                    for n in 'STATUS.MLP2_L2', 'STATUS.MLP2_L3A':
                        try:
                            del kwdict[n]
                        except NameError:
                            pass
                    print(f'{self._ts()} {kwdict}', file=self.kwlog, flush=True)
                except:
                    pass

                self.statusDict.update({k: changed[k] for k in self.statusDict if k in changed})

                self.actor.tracker.update(self.statusDict, changed.copy())
            self.logger.warn('quitEvent on gcam listener...')

        except KeyboardInterrupt as e:
            quitEvent.set()

    def connect(self):
        # setup (use the Gen2 host, user name and password you are advised by
        # observatory personnel)

        class Options:
            pass
        options = Options()
        options.streamhost='g2stat.sum.subaru.nao.ac.jp'
        options.stream_username = "none"
        options.stream_password = "none"
        options.host='g2db.sum.subaru.nao.ac.jp'
        options.username='pfs'
        options.password='Zl7b247ZlKN8p'

        sc = StatusClient(host=options.host, username=options.username,
                          password=options.password)
        sc.connect()

        # fetch a dictionary
        d = {'FITS.SBR.RA_CMD': None,
             'FITS.SBR.DEC_CMD': None,
             'FITS.SBR.RA': None,
             'FITS.SBR.DEC': None,
             'STATL.RA_OFFSET': None,
             'STATL.DEC_OFFSET': None,
             'FITS.SBR.ALTITUDE': None,
             'STATL.TELDRIVE': None,
             'STATL.DOMESHUTTER_POS': None,
        }

        sc.fetch(d)
        self.statusDict = d

        ss = StatusStream(host=options.streamhost, username=options.stream_username,
                          password=options.stream_password)
        ss.connect()

        # create a queue to receive the status updates
        status_q = queue.Queue()
        # shared event to signal termination of processing
        ev_quit = threading.Event()
        self.quitEvent = ev_quit

        if not hasattr(self.actor, 'tracker') or self.actor.tracker is None:
            self.actor.tracker = sunssTracker.SunssTracker(self.actor)

        # start a thread to put status updates on the queue
        t = threading.Thread(target=ss.subscribe_loop, args=[ev_quit, status_q])
        t.daemon = True
        self.gcamThread = t
        t.start()

        # Start a thread to run the actual SuNSS tracker
        trackerThread = threading.Thread(target=self.listener, kwargs=dict(quitEvent=ev_quit,
                                                                           gcamQueue=status_q))
        trackerThread.daemon = True
        self.trackerThread = trackerThread
        trackerThread.start()
