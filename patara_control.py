"""
Created on Jul 25, 2018

@author: Filip Lindau
"""

# from twisted.internet import reactor, protocol
# from pymodbus.client.async import ModbusClientProtocol
from pymodbus.client.sync import ModbusTcpClient as ModbusClient
from twisted_cut import defer, TangoTwisted
import patara_parameters as pp
import logging
import time
import Queue
import threading

logging.basicConfig(level=logging.WARNING)


class PataraControl(object):
    def __init__(self, ip="172.16.109.70", port=501, slave_id=1):
        self.client = None
        self.connected = False
        self.read_len = 64
        self.ip = ip
        self.port = port
        self.slave_id = slave_id
        self.patara_data = pp.PataraHardwareParameters()

        self.command_queue = Queue.Queue()
        self.lock = threading.Lock()
        self.response_pending = False
        self.deferred = None

    def init_client(self):
        """
        Initialize the connection with patara modbus device.
        :return:
        """
        self.client = ModbusClient(self.ip, self.port)
        self.client.connect()
        self.connected = True

    def close_client(self):
        if self.client is not None:
            self.client.close()
        self.client = None
        self.connected = False

    def read_coils(self):
        for r in self.patara_data.coil_read_range:
            d = TangoTwisted.defer_to_thread(self.client.read_coils, r[0], r[1]-r[0], unit=self.slave_id)
        return d

    def process_queue(self):
        if self.response_pending is False:
            try:
                with self.lock:
                    cmd = self.command_queue.get_nowait()
            except Queue.Empty:
                logging.debug("Queue empty. Exit processing")
                return
            self.deferred = cmd()
            self.response_pending = True
            self.deferred.add_callbacks(self.command_done, self.command_error)
            self.deferred.add_callback(self.process_queue)

    def add_command(self, cmd):
        logging.info("Adding command {0} to queue".format(str(cmd)))
        with self.lock:
            self.command_queue.put(cmd)

    def command_done(self, response):
        self.response_pending = False

    def command_error(self, err):
        logging.error(str(err))
        self.response_pending = False
