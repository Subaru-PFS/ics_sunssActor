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

        self.connect()

    def __del__(self):
        self.logger.warn(f'text="del thread_count={threading.active_count()}"')
        self.quitEvent.set()

    def start(self, cmd=None):
        cmd.warn(f'text="start thread_count={threading.active_count()}"')

    def stop(self, cmd=None):
        cmd.warn(f'text="stopping thread_count={threading.active_count()}"')
        self.quitEvent.set()
        time.sleep(1)
        cmd.warn(f'text="stopped thread_count={threading.active_count()}"')

    def _convertRaDecToDegrees(self, raStr, decStr):
        here = coords.FK5(ra=coords.Angle(raStr, unit='hourangle'),
                          dec=coords.Angle(decStr, unit='deg'))
        return here.ra.deg, here.dec.deg

    def listener(self, quitEvent=None, gcamQueue=None):
        mhsDict = dict(ra_cmd=None, dec_cmd=None,
                       ra=None, dec=None,
                       ra_offset=None, dec_offset=None,
                       alt=None, driveMode=None,
                       shutter=None)

        # consume items from queue
        try:
            print("consuming on queue...")
            while not quitEvent.is_set():
                try:
                    envelope = gcamQueue.get(timeout=0.5)
                except queue.Empty:
                    continue
                changed = envelope['status']
                # self.logger.info(f'from gcam: {changed} {envelope}')
                self.statusDict.update({k: changed[k] for k in self.statusDict if k in changed})

                self.tracker.update(self.statusDict, changed.copy())
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
        self.statusDict = d

        ss = StatusStream(host=options.streamhost, username=options.stream_username,
                          password=options.stream_password)
        ss.connect()

        # create a queue to receive the status updates
        status_q = queue.Queue()
        # shared event to signal termination of processing
        ev_quit = threading.Event()
        self.quitEvent = ev_quit

        self.tracker = sunssTracker.SunssTracker()

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
