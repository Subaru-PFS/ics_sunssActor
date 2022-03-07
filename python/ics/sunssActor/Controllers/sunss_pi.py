from importlib import reload

import numpy as np

import logging
import socket
import time

from ics.sunssActor.Controllers import bufferedSocket
reload(bufferedSocket)

class NonClosingSocket(object):
    def __init__(self, s):
        self.s = s
    def close(self):
        return
    def __getattr__(self, attr):
        return getattr(self.s, attr)
        
class DeviceIO(object):
    def __init__(self, name,
                 EOL=b'\n',
                 keepOpen=False,
                 loglevel=logging.DEBUG):

        self.logger = logging.getLogger('temps')
        self.logger.setLevel(loglevel)

        self.device = None if keepOpen else False
        self.EOL = EOL

    def connect(self, cmd=None, timelim=1.0):
        if self.device:
            return self.device
        
        s = self._connect(cmd=cmd, timelim=timelim)

        if self.device is None:
            self.device = s
            
        if self.device is False:
            return NonClosingSocket(s)
        else:
            return s
    
    def disconnect(self, cmd=None):
        if self.device in (None, False):
            return
        s = self.device
        self.device = None

        socket.socket.close(s)
        
class SocketIO(DeviceIO):
    def __init__(self, host, port, *argl, **argv):
        DeviceIO.__init__(self, *argl, **argv)
        self.host = host
        self.port = port

        self.ioBuffer = bufferedSocket.BufferedSocket('tempsio')
        
    def _connect(self, cmd=None, timelim=1.0):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timelim)
        except Exception as e:
            if cmd is not None:
                cmd.warn('text="failed to create socket: %s"' % (e))
            raise
 
        try:
            s.connect((self.host, self.port))
        except Exception as e:
            if cmd is not None:
                cmd.warn('text="failed to connect socket%s"' % (e))
            raise

        return s

    def readOneLine(self, sock=None, timelim=1.0, cmd=None):
        if sock is None:
            sock = self.connect(cmd=cmd)
            
        ret = self.ioBuffer.getOneResponse(sock, timeout=timelim, cmd=cmd)
        
        sock.close()
        
        return ret

    def sendOneCommand(self, cmdStr, timelim=1.0, sock=None, cmd=None):
        if cmd is None:
            cmd = self.actor.bcast

        if isinstance(cmdStr, str):
            cmdStr = cmdStr.encode('latin-1')
            
        fullCmd = b"%s%s" % (cmdStr, self.EOL)
        self.logger.debug('sending %r', fullCmd)
        cmd.diag('text="sending %r"' % fullCmd)

        if sock is None:
            sock = self.connect()
        
        try:
            sock.sendall(fullCmd)
        except socket.error as e:
            cmd.warn('text="failed to create send command to %s: %s"' % (self.name, e))
            raise

        ret = self.readOneLine(timelim=timelim, sock=sock, cmd=cmd)

        self.logger.debug('received %r', ret)
        cmd.diag('text="received %r"' % ret)

        return ret.strip()

class sunss_pi(object):
    def __init__(self, actor, name,
                 loglevel=logging.DEBUG):

        self.name = name
        self.actor = actor
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(loglevel)

        self.EOL = b'\n'
        
        host = self.actor.config.get(self.name, 'host')
        port = int(self.actor.config.get(self.name, 'port'))

        self.dev = SocketIO(host, port, name, self.EOL,
                            keepOpen=False,
                            loglevel=loglevel)

    def start(self, cmd=None):
        pass

    def stop(self, cmd=None):
        pass

    def sunssCmd(self, cmdStr, timelim=1.0, cmd=None):
        if cmd is None:
            cmd = self.actor.bcast

        cmd.inform(f'text="sending to sunss: {cmdStr}"')
        ret = self.dev.sendOneCommand(cmdStr, timelim=timelim, cmd=cmd)
        return ret

