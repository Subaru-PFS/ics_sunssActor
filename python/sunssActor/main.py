#!/usr/bin/env python

import argparse
import logging
from twisted.internet import reactor

import actorcore.ICC

class OurActor(actorcore.ICC.ICC):
    def __init__(self, name, productName=None, configFile=None, site=None,
                 logLevel=logging.INFO):

        # This sets up the connections to/from the hub, the logger, and the twisted reactor.
        #
        actorcore.ICC.ICC.__init__(self, name,
                                   productName=productName, 
                                   configFile=configFile)
        self.logger.setLevel(logLevel)

        self.everConnected = False

        self.monitors = dict()
        self.statusLoopCB = self.statusLoop

    def reloadConfiguration(self, cmd):
        cmd.inform('sections=%08x,%r' % (id(self.config),
                                         self.config))

    def connectionMade(self):
        if self.everConnected is False:
            logging.info("Attaching all controllers...")
            self.allControllers = [s.strip() for s in self.config.get(self.name, 'startingControllers').split(',')]
            self.attachAllControllers()
            self.everConnected = True

            _needModels = [self.name, 'sps', 'iic']
            self.logger.info(f'adding models: {_needModels}')
            self.addModels(_needModels)
            self.logger.info(f'added models: {self.models.keys()}')

    def statusLoop(self, controller):
        try:
            self.callCommand("%s status" % (controller))
        except:
            pass
        
        if self.monitors[controller] > 0:
            reactor.callLater(self.monitors[controller],
                              self.statusLoopCB,
                              controller)
            
    def monitor(self, controller, period, cmd=None):
        if controller not in self.monitors:
            self.monitors[controller] = 0

        running = self.monitors[controller] > 0
        self.monitors[controller] = period

        if (not running) and period > 0:
            cmd.warn('text="starting %gs loop for %s"' % (self.monitors[controller],
                                                          controller))
            self.statusLoopCB(controller)
        else:
            cmd.warn('text="adjusted %s loop to %gs"' % (controller, self.monitors[controller]))

    def safeCall(self, cmd, actor, cmdStr, timeLim=60):
        cmdVar = self.cmdr.call(actor=actor, cmdStr=cmdStr, timeLim=timeLim, forUserCmd=cmd)

        if cmdVar.didFail:
            reply = cmdVar.replyList[-1]
            repStr = reply.keywords.canonical(delimiter=';')
            cmdHead = cmdStr.split(" ", 1)[0]
            cmd.warn(repStr.replace('command failed', f'{actor} {cmdHead} failed'))

        return cmdVar

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=None, type=str, nargs='?',
                        help='configuration file to use')
    parser.add_argument('--logLevel', default=logging.INFO, type=int, nargs='?',
                        help='logging level')
    args = parser.parse_args()

    theActor = OurActor(name='sunss',
                        productName='sunssActor',
                        configFile=args.config,
                        logLevel=args.logLevel)
    theActor.run()

if __name__ == '__main__':
    main()
