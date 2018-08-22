"""
Created on Jul 25, 2018

@author: Filip Lindau
"""

# from twisted.internet import reactor, protocol
# from pymodbus.client.async import ModbusClientProtocol
from pymodbus.client.sync import ModbusTcpClient as ModbusClient
from twisted_cut import defer, TangoTwisted, failure
import patara_parameters as pp
import logging
import time
import Queue
import threading

reload(pp)

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
        self.queue_pending_deferred = None

        self.state = "unknown"
        self.com0_state = "unknown"
        self.channel1_state = "unknown"
        self.shutter_state = False
        self.status = ""
        self.active_fault_list = list()
        self.active_interlock_list = list()

        self.setup_attr_params = dict()
        # self.setup_attr_params["shutter"] = False
        # self.setup_attr_params["emission"] = False
        # self.setup_attr_params["channel1_active_current"] = 13.4

        self.standby_polling_attrs = dict()
        self.standby_polling_attrs["input_registers"] = 0.3
        self.standby_polling_attrs["status"] = 0.3
        self.standby_polling_attrs["control"] = 0.5

        self.active_polling_attrs = dict()
        self.active_polling_attrs["input_registers"] = 0.3
        self.active_polling_attrs["status"] = 0.3
        self.active_polling_attrs["control"] = 0.5

        self.state_notifier_list = list()

    def init_client(self):
        """
        Initialize the connection with patara modbus device.
        :return:
        """
        logger.info("Initialize client connection")
        self.close_client()
        self.client = ModbusClient(self.ip, self.port)
        d = TangoTwisted.defer_to_thread(self.client.connect)
        d.addCallback(self.init_client_cb)
        d.addErrback(self.command_error)
        return d
        # retval = self.client.connect()
        # if retval is True:
        #     self.connected = True
        # else:
        #     self.connected = False
        # return self.connected

    def init_client_cb(self, result):
        if result is True:
            self.connected = True
        else:
            self.connected = False
        return self.connected

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
            d = TangoTwisted.defer_to_thread(self.client.read_coils, address=r[0], count=r[1]-r[0] + 1,
                                             unit=self.slave_id)
        return d

    def read_control_state_queue_cmd(self):
        """
        Read essential control bits from function 01, such as emission, standby, shutter
        :return:
        """
        min_addr = self.patara_data.coil_read_range[0][0]
        max_addr = self.patara_data.coil_read_range[0][1]
        logger.debug("Reading control state from {0} to {1}".format(min_addr, max_addr))
        d = TangoTwisted.defer_to_thread(self.client.read_coils, min_addr, max_addr - min_addr + 1,
                                         unit=self.slave_id)
        d.addCallbacks(self.process_control_state, self.client_error)
        return d

    def read_status_queue_cmd(self):
        """
        Read status bit from function 02.
        :return:
        """
        min_addr = self.patara_data.discrete_input_read_range[0][0]
        max_addr = self.patara_data.discrete_input_read_range[0][1]
        logger.debug("Reading status from {0} to {1}".format(min_addr, max_addr))
        d = TangoTwisted.defer_to_thread(self.client.read_discrete_inputs, min_addr, max_addr - min_addr + 1,
                                         unit=self.slave_id)
        d.addCallbacks(self.process_status, self.client_error)
        return d

    def defer_to_queue(self, f, *args, **kwargs):
        logger.debug("Deferring {0} with args {1}, kwargs {2} to queue".format(f, args, kwargs))
        d = defer.Deferred(canceller=self.cancel_queue_cmd_from_deferred)
        # cmd = (d, f, args, kwargs)
        # cmd = d
        # d.addCallback(f, args, kwargs)
        # with self.lock:
        #     self.command_queue.put(cmd)
        # return d
        #
        d.addCallback(self.queue_cb, f, *args, **kwargs)
        with self.lock:
            self.command_queue.put(d)
        return d

    def cancel_queue_cmd_from_deferred(self, d):
        logger.info("Cancelling {0}".format(d))
        cmd_list = list()
        with self.lock:
            while self.command_queue.empty() is False:
                cmd = self.command_queue.get_nowait()
                if cmd != d:
                    cmd_list.append(cmd)
            for cmd in cmd_list:
                self.command_queue.put(cmd)

    def queue_cb(self, d_called, f, *args, **kwargs):
        """
        Start thread running function. Copy callbacks from calling
        deferred and clear them from the calling deferred, stalling
        callback execution until the thread completes.
        :param d_called: Result from callback of d_callback (it sends itself as result)
        :param f: Function to execute in thread
        :param args: Arguments to function
        :param kwargs: Keyword arguments to function
        :return: Nada
        """
        d = TangoTwisted.defer_to_thread(f, *args, **kwargs)
        d.callbacks = d_called.callbacks
        d.addCallbacks(self.command_done, self.command_error)
        d_called.callbacks = []

    def process_queue(self):
        if self.response_pending is False:
            try:
                with self.lock:
                    d_cmd = self.command_queue.get_nowait()
            except Queue.Empty:
                # logger.debug("Queue empty. Exit processing")
                return
            self.queue_pending_deferred = d_cmd
            logger.debug("Deferring {0}".format(d_cmd))
            self.response_pending = True
            d_cmd.callback(d_cmd)

        # if self.response_pending is False:
        #     try:
        #         with self.lock:
        #             cmd_tuple = self.command_queue.get_nowait()
        #     except Queue.Empty:
        #         logger.debug("Queue empty. Exit processing")
        #         return
        #     self.queue_pending_deferred = cmd_tuple[0]
        #     logger.debug("Deferring {0} with args {1}, kwargs {2} to thread".format(
        #         cmd_tuple[1], cmd_tuple[2], cmd_tuple[3]))
        #     d = TangoTwisted.defer_to_thread(cmd_tuple[1], *cmd_tuple[2], **cmd_tuple[3])
        #     self.response_pending = True
        #     d.addCallbacks(self.command_done, self.command_error)

    def add_command(self, d_cmd):
        """
        Add a deferred with command function as callback.
        *DO NOT USE* - use defer to queue instead
        :param d_cmd: Deferred with command as callback
        :return:
        """
        logger.info("Adding command {0} to queue".format(str(d_cmd)))
        with self.lock:
            self.command_queue.put(d_cmd)

    def command_done(self, response):
        logger.debug("Command done.")
        self.response_pending = False
        try:
            self.queue_pending_deferred.callback(response)
        except defer.AlreadyCalledError:
            logger.error("Pending deferred already called")
        self.process_queue()

    def command_error(self, err):
        logger.error(str(err))
        self.response_pending = False
        self.queue_pending_deferred.errback(err)

    def write_parameter(self, name, value, process_now=True, readback=True):
        """
        Write a single named parameter to the Patara. If readback is True the same parameter is scheduled
        to be read after the write. The retured deferred fires when the result is ready.

        :param name: Name of the parameter according the eDrive User Manual
        :param value: Value to write
        :param process_now: True if the queue should be processes immediately
        :param readback: True if the value should be read back from the Patara
        :return: Deferred that fires when the result is ready
        """
        p = self.get_parameter(name)
        if p is None:
            err = "Name {0} not in parameter dictionary".format(name)
            logger.error(err)
            d = defer.Deferred()
            fail = failure.Failure(AttributeError(err))
            d.errback(fail)
            return d
        addr = p.get_address()
        func = p.get_function_code()
        (factor, offset) = p.get_conversion()
        w_val = int((value - offset) / factor)
        logger.debug("Writing to {0}. Addr: {1}, func {2}, value {3}".format(name, addr, func, w_val))
        if func == 1:
            f = self.client.write_coil
        elif func == 3:
            f = self.client.write_register
        else:
            err = "Wrong function code {0}, should be 1, or 3".format(func)
            logger.error(err)
            d = defer.Deferred()
            fail = failure.Failure(AttributeError(err))
            d.errback(fail)
            return d

        d = self.defer_to_queue(f, addr, value, unit=self.slave_id)
        d.addErrback(self.client_error)
        if readback is True:
            d = self.read_parameter(name, process_now)
        if process_now is True:
            self.process_queue()
        return d

    def read_parameter(self, name, process_now=True):
        """
        Read a single named parameter from the Patara and store the result in the parameter
        dictionary. The retured deferred fires when the result is ready.

        :param name: Name of the parameter according the eDrive User Manual
        :param process_now: True if the queue should be processes immediately
        :return: Deferred that fires when the result is ready
        """
        p = self.get_parameter(name)
        if p is None:
            err = "Name {0} not in parameter dictionary".format(name)
            logger.error(err)
            d = defer.Deferred()
            fail = failure.Failure(AttributeError(err))
            d.errback(fail)
            return d
        addr = p.get_address()
        func = p.get_function_code()
        logger.debug("Reading {0}. Addr: {1}, func {2}".format(name, addr, func))
        if func == 1:
            f = self.client.read_coils
        elif func == 2:
            f = self.client.read_discrete_inputs
        elif func == 3:
            f = self.client.read_holding_registers
        elif func == 4:
            f = self.client.read_input_registers
        else:
            err = "Wrong function code {0}, should be 1, 2, 3, or 4".format(func)
            logger.error(err)
            d = defer.Deferred()
            fail = failure.Failure(AttributeError(err))
            d.errback(fail)
            return d

        d = self.defer_to_queue(f, addr, 1, unit=self.slave_id)
        d.addCallback(self.process_parameters, min_addr=addr)
        d.addErrback(self.client_error)
        if process_now is True:
            self.process_queue()
        return d

    def read_control_state(self, process_now=True, **kwargs):
        """
        Place a read_coils command on the command queue. Returns a deferred that
        fires when the command has finsihed executing.

        Which read_coils to read are selected with range_id or min_addr + max_attr.
        If nothing is specified, range_id=0 is presumed.

        :param process_now: True if the queue should be processed immediately.
        :param kwargs:
            range_id: integer to index read_range variable in patara data
            min_addr: starting read_coil to read
            max_addr: end read_coil to read
        :return:
        """
        if "range_id" in kwargs:
            range_id = kwargs["range_id"]
        else:
            range_id = 0
        if "min_addr" in kwargs:
            min_addr = kwargs["min_addr"]
        else:
            min_addr = self.patara_data.coil_read_range[range_id][0]
        if "max_addr" in kwargs:
            max_addr = kwargs["max_addr"]
        else:
            max_addr = self.patara_data.coil_read_range[range_id][1]
        # min_addr = self.patara_data.coil_read_range[0][0]
        # max_addr = self.patara_data.coil_read_range[0][1]
        logger.debug("Reading control state from {0} to {1}".format(min_addr, max_addr))

        d = self.defer_to_queue(self.client.read_coils, min_addr, max_addr - min_addr + 1,
                                unit=self.slave_id)
        d.addCallback(self.process_control_state, min_addr=min_addr)
        d.addErrback(self.client_error)
        if process_now is True:
            self.process_queue()
        return d

    def read_status(self, process_now=True, **kwargs):
        """
        Place a read_discrete_inputs command on the command queue. Returns a deferred that
        fires when the command has finsihed executing.

        Which discrete_inputs to read are selected with range_id or min_addr + max_attr.
        If nothing is specified, range_id=0 is presumed.

        :param process_now: True if the queue should be processed immediately.
        :param kwargs:
            range_id: integer to index read_range variable in patara data
            min_addr: starting discrete_input to read
            max_addr: end discrete_input to read
        :return:
        """
        if "range_id" in kwargs:
            range_id = kwargs["range_id"]
        else:
            range_id = 0
        if "min_addr" in kwargs:
            min_addr = kwargs["min_addr"]
        else:
            min_addr = self.patara_data.discrete_input_read_range[range_id][0]
        if "max_addr" in kwargs:
            max_addr = kwargs["max_addr"]
        else:
            max_addr = self.patara_data.discrete_input_read_range[range_id][1]
        # min_addr = self.patara_data.discrete_input_read_range[0][0]
        # max_addr = self.patara_data.discrete_input_read_range[0][1]
        logger.debug("Reading status from {0} to {1}".format(min_addr, max_addr))

        d = self.defer_to_queue(self.client.read_discrete_inputs, min_addr, max_addr - min_addr + 1,
                                unit=self.slave_id)
        d.addCallback(self.process_status, min_addr=min_addr)
        d.addErrback(self.client_error)
        if process_now is True:
            self.process_queue()
        return d

    def read_input_registers(self, process_now=True, **kwargs):
        """
        Place a read_input_registers command on the command queue. Returns a deferred that
        fires when the command has finsihed executing.

        Which registers to read are selected with range_id or min_addr + max_attr.
        If nothing is specified, range_id=0 is presumed.

        :param process_now: True if the queue should be processed immediately.
        :param kwargs:
            range_id: integer to index read_range variable in patara data
            min_addr: starting register to read
            max_addr: end register to read
        :return:
        """
        if "range_id" in kwargs:
            range_id = kwargs["range_id"]
        else:
            range_id = 0
        if "min_addr" in kwargs:
            min_addr = kwargs["min_addr"]
        else:
            min_addr = self.patara_data.input_register_read_range[range_id][0]
        if "max_addr" in kwargs:
            max_addr = kwargs["max_addr"]
        else:
            max_addr = self.patara_data.input_register_read_range[range_id][1]
        logger.debug("Reading input registers from {0} to {1}".format(min_addr, max_addr))

        d = self.defer_to_queue(self.client.read_input_registers, min_addr, max_addr - min_addr + 1,
                                unit=self.slave_id)
        d.addCallback(self.process_input_registers, min_addr=min_addr)
        d.addErrback(self.client_error)
        if process_now is True:
            self.process_queue()
        return d

    def process_parameters(self, response, min_addr=0):
        logger.debug("Processing parameters response: {0}".format(response))
        func = response.function_code
        if func == 1 or func == 2:
            data = response.bits
        else:
            data = response.registers
        t = time.time()
        result = dict()
        for addr, reg in enumerate(data):
            logger.debug("Addr: {0}, reg {1}".format(addr + min_addr, reg))
            set_res = self.patara_data.set_parameter_from_modbus_addr(func, addr + min_addr, reg, t)
            logger.debug("Set result: {0}".format(set_res))
            name = self.patara_data.get_name_from_modbus_addr(func, addr + min_addr)
            try:
                value = self.patara_data.parameters[name].get_value()
            except KeyError:
                logger.error("KeyError for name {0}, addr {1}".format(name, addr + min_addr))
                continue
            logger.debug("Name: {0}, value: {1}".format(name, value))
            result[name] = value
        return result

    def process_control_state(self, response, min_addr=0):
        logger.debug("Processing status response: {0}".format(response))
        data = response.bits
        t = time.time()
        result = dict()
        for addr, bit in enumerate(data):
            self.patara_data.set_parameter_from_modbus_addr(1, addr + min_addr, bit, t)
            name = self.patara_data.get_name_from_modbus_addr(1, addr + min_addr)
            result[name] = bit
        return result

    def process_input_registers(self, response, min_addr=0):
        logger.debug("Processing input registers response: {0}".format(response))
        data = response.registers
        t = time.time()
        result = dict()
        state = None
        channel1_state = None
        shutter_state = None
        com0_state = None
        for addr, reg in enumerate(data):
            logger.debug("Addr: {0}, reg {1}".format(addr + min_addr, reg))
            set_res = self.patara_data.set_parameter_from_modbus_addr(4, addr + min_addr, reg, t)
            logger.debug("Set result: {0}".format(set_res))
            name = self.patara_data.get_name_from_modbus_addr(4, addr + min_addr)
            try:
                value = self.patara_data.parameters[name].get_value()
            except KeyError:
                logger.error("KeyError for name {0}, addr {1}".format(name, addr + min_addr))
                continue
            logger.debug("Name: {0}, value: {1}".format(name, value))
            result[name] = value
            if name in ["fault_state", "off_state", "standby_state", "pre-fire_state", "active_state"]:
                if value is True:
                    state = name
            elif name in ["channel1_off_state", "channel1_standby", "channel1_active", "channel1_fault_state"]:
                if value is True:
                    channel1_state = name
            elif name in ["com0_off_state", "com0_standby_state", "com0_active_state", "com0_fault_state"]:
                    if value is True:
                        com0_state = name
            elif name == "laser_shutter_state":
                shutter_state = value
        if state != self.get_state():
            self.set_state(state)
        self.channel1_state = channel1_state
        self.com0_state = com0_state
        self.shutter_state = shutter_state
        return result

    def process_status(self, response, min_addr=0):
        logger.debug("Processing status response: {0}".format(response))
        data = response.bits
        t = time.time()
        faults = list()
        interlocks = list()
        for addr, bit in enumerate(data):
            self.patara_data.set_parameter_from_modbus_addr(2, addr + min_addr, bit, t)
            name = self.patara_data.get_name_from_modbus_addr(2, addr + min_addr)
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
                        faults.append(name)
                elif "interlock" in name:
                    if bit == 1:
                        interlocks.append(name)
        with self.lock:
            self.active_fault_list = faults
            self.active_interlock_list = interlocks
        return faults, interlocks

    def client_error(self, err):
        logger.error("Modbus error: {0}".format(err))
        self.init_client()

    def get_parameter(self, name):
        """
        Get a stored patara parameter with name. If the parameter is not in the dictionary
        return None.
        :param name: Name of parameter according to Patara eDrive User Manual
        :return: PataraParameter (Retrieve value with .get_value method)
        """
        with self.lock:
            try:
                p = self.patara_data.parameters[name]
            except KeyError:
                p = None
        return p

    def get_parameters(self, name_list):
        p_list = list()
        for name in name_list:
            with self.lock:
                try:
                    p = self.patara_data.parameters[name]
                except KeyError:
                    p = None
            p_list.append(p)
        return p_list

    def set_status(self, new_status):
        self.status = new_status

    def get_status(self):
        return self.status

    def set_state(self, new_state):
        if new_state != self.state:
            self.state = new_state
            for notifier in self.state_notifier_list:
                notifier(new_state)

    def get_state(self):
        return self.state

    def add_state_notifier(self, notifier):
        if notifier not in self.state_notifier_list:
            self.state_notifier_list.append(notifier)


if __name__ == "__main__":
    pc = PataraControl("172.16.109.70", 502, 1)
    pc.init_client()
