"""
Created on Jul 25, 2018

@author: Filip Lindau
"""

# from twisted.internet import reactor, protocol
# from pymodbus.client.async import ModbusClientProtocol
from pymodbus.client.sync import ModbusTcpClient as ModbusClient
from twisted_cut import defer, TangoTwisted
import patara_parameters as pp
reload(pp)
import logging
import time
import Queue
import threading

logger = logging.getLogger("PataraControl")
logger.setLevel(logging.DEBUG)
while len(logger.handlers):
    logger.removeHandler(logger.handlers[0])

f = logging.Formatter("%(asctime)s - %(name)s.   %(funcName)s - %(levelname)s - %(message)s")
fh = logging.StreamHandler()
fh.setFormatter(f)
logger.addHandler(fh)
logger.setLevel(logging.DEBUG)


class PataraControl(object):
    def __init__(self, ip="172.16.109.70", port=502, slave_id=1):
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

        self.state = "unknown"
        self.com0_state = "unknown"
        self.channel1_state = "unknown"
        self.fault = list()

    def init_client(self):
        """
        Initialize the connection with patara modbus device.
        :return:
        """
        logger.info("Initialize client connection")
        self.close_client()
        self.client = ModbusClient(self.ip, self.port)
        retval = self.client.connect()
        if retval is True:
            self.connected = True
        else:
            self.connected = False

    def close_client(self):
        """
        Close connection to client
        :return:
        """
        logger.info("Close connection to client")
        if self.client is not None:
            self.client.close()
        self.client = None
        self.connected = False

    def read_coils(self):
        for r in self.patara_data.coil_read_range:
            d = TangoTwisted.defer_to_thread(self.client.read_coils, address=r[0], count=r[1]-r[0],
                                             unit=self.slave_id)
        return d

    def read_status(self):
        min_addr = self.patara_data.discrete_input_read_range[0][0]
        max_addr = self.patara_data.discrete_input_read_range[0][1]
        logger.debug("Reading status from {0} to {1}".format(min_addr, max_addr))
        d = TangoTwisted.defer_to_thread(self.client.read_discrete_inputs, min_addr, max_addr - min_addr,
                                         unit=self.slave_id)
        d.addCallbacks(self.process_status, self.client_error)
        return d

    def process_status(self, response):
        logger.debug("Processing status response: {0}".format(response))
        data = response.bits
        t = time.time()
        self.fault = list()
        for addr, bit in enumerate(data):
            self.patara_data.set_parameter_from_modbus_addr(2, addr, bit, t)
            name = self.patara_data.get_name_from_modbus_addr(2, addr)
            if name is not None:
                if addr < 5:
                    if bit == 1:
                        self.state = name
                elif 32 <= addr <= 35:
                    if bit == 1:
                        self.channel1_state = name
                elif 80 <= addr <= 83:
                    if bit == 1:
                        self.com0_state = name
                elif "fault" in name:
                    if bit == 1:
                        self.fault.append(name)
        return response

    def client_error(self, err):
        logger.error("Modbus error: {0}".format(err))
        self.init_client()

    def process_queue(self):
        if self.response_pending is False:
            try:
                with self.lock:
                    cmd = self.command_queue.get_nowait()
            except Queue.Empty:
                logger.debug("Queue empty. Exit processing")
                return
            self.deferred = cmd()
            self.response_pending = True
            self.deferred.add_callbacks(self.command_done, self.command_error)
            self.deferred.add_callback(self.process_queue)

    def add_command(self, cmd):
        logger.info("Adding command {0} to queue".format(str(cmd)))
        with self.lock:
            self.command_queue.put(cmd)

    def command_done(self, response):
        self.response_pending = False

    def command_error(self, err):
        logger.error(str(err))
        self.response_pending = False


if __name__ == "__main__":
    pc = PataraControl("172.16.109.70", 502, 1)
    pc.init_client()
