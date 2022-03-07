from builtins import object
import select
import logging

from opscore.utility.qstr import qstr

class BufferedSocket(object):
    """ Buffer the input from a socket and block it into lines. """

    def __init__(self, name, sock=None, loggerName=None, EOL=b'\n', timeout=1.0,
                 logLevel=logging.INFO):
        self.EOL = EOL
        self.sock = sock
        self.name = name
        self.logger = logging.getLogger(loggerName)
        self.logger.setLevel(logLevel)
        self.timeout = timeout

        self.buffer = b''

    def getOutput(self, sock=None, timeout=None, cmd=None):
        """ Block/timeout for input, then return all (<=1kB) available input. """
        
        if sock is None:
            sock = self.sock
        if timeout is None:
            timeout = self.timeout

        readers, writers, broken = select.select([sock.fileno()], [], [], timeout)
        if len(readers) == 0:
            msg = "Timed out reading character from %s" % self.name
            self.logger.warning(msg)
            if cmd is not None:
                cmd.warn('text="%s"' % msg)
            raise IOError(msg)
        return sock.recv(1024)

    def getOneResponse(self, sock=None, timeout=None, cmd=None):
        """ Return the next available complete line. Fetch new input if necessary. 

        Args
        ----
        sock : socket
           Uses self.sock if not set.
        timeout : float
           Uses self.timeout if not set.

        Returns
        -------
        str or None : a single line of response text, with EOL character(s) stripped.

        """

        while self.buffer.find(self.EOL) == -1:
            try:
                more = self.getOutput(sock=sock, timeout=timeout, cmd=cmd)
            except IOError:
                return ''
            
            msg = '%s added: %r' % (self.name, more)
            self.logger.debug(msg)
            if cmd:
                cmd.diag('text=%s' % (qstr(msg)))
            self.buffer += more
            if more == b'':
                return ''
            
        eolAt = self.buffer.find(self.EOL)
        ret = self.buffer[:eolAt]

        self.buffer = self.buffer[eolAt+len(self.EOL):]

        return ret.decode('latin-1')



