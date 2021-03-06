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
import numpy as np

reload(pp)

logger = logging.getLogger("PataraControl")
while len(logger.handlers):
    logger.removeHandler(logger.handlers[0])
logger.setLevel(logging.DEBUG)
f = logging.Formatter("%(asctime)s - %(name)s.   %(funcName)s - %(levelname)s - %(message)s")
fh = logging.StreamHandler()
fh.setFormatter(f)
logger.addHandler(fh)


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

        self.logger = logging.getLogger("PataraControl")
        while len(self.logger.handlers):
            self.logger.removeHandler(self.logger.handlers[0])

        # f = logging.Formatter("%(asctime)s - %(module)s.   %(funcName)s - %(levelname)s - %(message)s")
        f = logging.Formatter("%(asctime)s - %(name)s.   %(funcName)s - %(levelname)s - %(message)s")
        fh = logging.StreamHandler()
        fh.setFormatter(f)
        self.logger.addHandler(fh)
        self.logger.setLevel(logging.INFO)

    def init_client(self):
        """
        Initialize the connection with patara modbus device.
        :return:
        """
        self.logger.info("Initialize client connection")
        self.close_client()
        self.client = ModbusClient(self.ip, self.port)
        d = TangoTwisted.defer_to_thread(self.client.connect)
        d.addCallback(self.init_client_cb)
        d.addErrback(self.command_error)
        return d

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
        self.logger.info("Close connection to client")
        with self.lock:
            self.command_queue = Queue.Queue()
        self.cancel_queue_cmd_from_deferred(self.queue_pending_deferred)
        self.queue_pending_deferred = None
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
        self.logger.debug("Reading control state from {0} to {1}".format(min_addr, max_addr))
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
        self.logger.debug("Reading status from {0} to {1}".format(min_addr, max_addr))
        d = TangoTwisted.defer_to_thread(self.client.read_discrete_inputs, min_addr, max_addr - min_addr + 1,
                                         unit=self.slave_id, canceller=self.dummy_canceller)
        d.addCallbacks(self.process_status, self.client_error)
        return d

    def defer_to_queue(self, f, *args, **kwargs):
        self.logger.debug("Deferring {0} with args {1}, kwargs {2} to queue".format(f, args, kwargs))
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
        self.logger.info("Cancelling {0}".format(d))
        if isinstance(d, defer.Deferred):
            cmd_list = list()
            with self.lock:
                while self.command_queue.empty() is False:
                    cmd = self.command_queue.get_nowait()
                    if cmd != d:
                        cmd_list.append(cmd)
                    else:
                        self.logger.info("Found deferred in list. Remove it.")
                for cmd in cmd_list:
                    self.command_queue.put(cmd)

    def dummy_canceller(self, d):
        self.logger.info("Dummy cancelling {0}".format(d))

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
        d = TangoTwisted.defer_to_thread(f, canceller=self.dummy_canceller, *args, **kwargs)
        d.callbacks = d_called.callbacks
        d.addCallbacks(self.command_done, self.command_error)
        d_called.callbacks = []

    def process_queue(self):
        if self.response_pending is False:
            try:
                with self.lock:
                    if self.command_queue is not None:
                        d_cmd = self.command_queue.get_nowait()
            except Queue.Empty:
                # self.logger.debug("Queue empty. Exit processing")
                return
            self.queue_pending_deferred = d_cmd
            self.logger.debug("Deferring {0}".format(d_cmd))
            self.response_pending = True
            d_cmd.callback(d_cmd)

    def add_command(self, d_cmd):
        """
        Add a deferred with command function as callback.
        *DO NOT USE* - use defer to queue instead
        :param d_cmd: Deferred with command as callback
        :return:
        """
        self.logger.info("Adding command {0} to queue".format(str(d_cmd)))
        with self.lock:
            self.command_queue.put(d_cmd)

    def command_done(self, response):
        self.logger.debug("Command done.")
        self.response_pending = False
        try:
            if self.queue_pending_deferred.called is False:
                self.queue_pending_deferred.callback(response)
        except defer.AlreadyCalledError:
            self.logger.error("Pending deferred already called")
        self.process_queue()
        # self.logger.info("Command done finished. Returning response {0}".format(response))
        return response

    def command_error(self, err):
        self.logger.error(str(err))
        self.response_pending = False
        self.queue_pending_deferred.errback(err)
        return err

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
            self.logger.error(err)
            d = defer.Deferred()
            fail = failure.Failure(AttributeError(err))
            d.errback(fail)
            return d
        addr = p.get_address()
        func = p.get_function_code()
        (factor, offset) = p.get_conversion()
        w_val = np.uint16((value - offset) / factor)
        self.logger.info("Writing to {0}. Addr: {1}, func {2}, value {3}".format(name, addr, func, w_val))
        if func == 1:
            f = self.client.write_coil
        elif func == 3:
            f = self.client.write_register
        else:
            err = "Wrong function code {0}, should be 1, or 3".format(func)
            self.logger.error(err)
            d = defer.Deferred()
            fail = failure.Failure(AttributeError(err))
            d.errback(fail)
            return d

        d = self.defer_to_queue(f, addr, w_val, unit=self.slave_id)
        # d = defer.Deferred()
        d.addErrback(self.client_error)
        if readback is True:
            d = self.read_parameter(name, process_now)
        if process_now is True:
            self.process_queue()
        return d

    def clear_fault(self):
        self.logger.info("Sending CLEAR FAULT command")
        self.write_parameter("clear_fault", True, process_now=True, readback=False)

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
            self.logger.error(err)
            d = defer.Deferred()
            fail = failure.Failure(AttributeError(err))
            d.errback(fail)
            return d
        addr = p.get_address()
        func = p.get_function_code()
        self.logger.debug("Reading {0}. Addr: {1}, func {2}".format(name, addr, func))
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
            self.logger.error(err)
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
        self.logger.debug("Reading control state from {0} to {1}".format(min_addr, max_addr))

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
        self.logger.debug("Reading status from {0} to {1}".format(min_addr, max_addr))

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
        self.logger.debug("Reading input registers from {0} to {1}".format(min_addr, max_addr))

        d = self.defer_to_queue(self.client.read_input_registers, min_addr, max_addr - min_addr + 1,
                                unit=self.slave_id)
        d.addCallback(self.process_input_registers, min_addr=min_addr)
        d.addErrback(self.client_error)
        if process_now is True:
            self.process_queue()
        return d

    def process_parameters(self, response, min_addr=0):
        self.logger.debug("Processing parameters response: {0}".format(response))
        func = response.function_code
        if func == 1 or func == 2:
            data = response.bits
        else:
            data = response.registers
        t = time.time()
        result = dict()
        for addr, reg in enumerate(data):
            self.logger.debug("Addr: {0}, reg {1}".format(addr + min_addr, reg))
            if addr == 16:
                self.logger.info("Read channel1_active_current: {0}".format(reg))
            set_res = self.patara_data.set_parameter_from_modbus_addr(func, addr + min_addr, reg, t)
            self.logger.debug("Set result: {0}".format(set_res))
            name = self.patara_data.get_name_from_modbus_addr(func, addr + min_addr)
            try:
                value = self.patara_data.parameters[name].get_value()
            except KeyError:
                self.logger.error("KeyError for name {0}, addr {1}".format(name, addr + min_addr))
                continue
            self.logger.debug("Name: {0}, value: {1}".format(name, value))
            result[name] = value
        return result

    def process_control_state(self, response, min_addr=0):
        self.logger.debug("Processing status response: {0}".format(response))
        try:
            data = response.bits
        except ValueError:
            return response
        t = time.time()
        result = dict()
        for addr, bit in enumerate(data):
            self.patara_data.set_parameter_from_modbus_addr(1, addr + min_addr, bit, t)
            name = self.patara_data.get_name_from_modbus_addr(1, addr + min_addr)
            result[name] = bit
        return result

    def process_input_registers(self, response, min_addr=0):
        self.logger.debug("Processing input registers response: {0}".format(response))
        try:
            data = response.registers
        except ValueError:
            return response
        t = time.time()
        result = dict()
        for addr, reg in enumerate(data):
            # self.logger.debug("Addr: {0}, reg {1}".format(addr + min_addr, reg))
            self.patara_data.set_parameter_from_modbus_addr(4, addr + min_addr, reg, t)
            # self.logger.debug("Set result: {0}".format(set_res))
            name = self.patara_data.get_name_from_modbus_addr(4, addr + min_addr)
            try:
                value = self.patara_data.parameters[name].get_value()
            except KeyError:
                # self.logger.error("KeyError for name {0}, addr {1}".format(name, addr + min_addr))
                continue
            # self.logger.debug("Name: {0}, value: {1}".format(name, value))
            result[name] = value
        return result

    def process_status(self, response, min_addr=0):
        self.logger.debug("Processing status response: {0}".format(response))
        try:
            data = response.bits
        except ValueError:
            return response
        t = time.time()
        faults = list()
        interlocks = list()
        state = None
        channel1_state = None
        shutter_state = None
        com0_state = None
        for addr, bit in enumerate(data):
            self.patara_data.set_parameter_from_modbus_addr(2, addr + min_addr, bit, t)
            name = self.patara_data.get_name_from_modbus_addr(2, addr + min_addr)
            try:
                value = self.patara_data.parameters[name].get_value()
            except KeyError:
                # self.logger.error("KeyError for name {0}, addr {1}".format(name, addr + min_addr))
                continue
            self.logger.debug("Name: {0}, value: {1}".format(name, value))
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
            # if name is not None:
            #     if addr < 5:
            #         if bit == 1:
            #             self.state = name
            #     elif 32 <= addr <= 35:
            #         if bit == 1:
            #             self.channel1_state = name
            #     elif 80 <= addr <= 83:
            #         if bit == 1:
            #             self.com0_state = name
            elif "fault" in name:
                if value is True:
                    faults.append(name)
            elif "interlock" in name:
                if value is True:
                    interlocks.append(name)
        self.channel1_state = channel1_state
        self.com0_state = com0_state
        self.set_state(state, shutter_state, faults, interlocks)

        # with self.lock:
        #     self.active_fault_list = faults
        #     self.active_interlock_list = interlocks
        return response

    def client_error(self, err):
        self.logger.error("Modbus error: {0}".format(err))
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

    def get_fault_list(self):
        with self.lock:
            # Use copy here
            fl = self.active_fault_list
        return fl

    def get_interlock_list(self):
        with self.lock:
            # Use copy here
            il = self.active_interlock_list
        return il

    def set_status(self, new_status=None):
        if new_status is not None:
            self.status = new_status
        for notifier in self.state_notifier_list:
            new_status = self.get_status()
            new_state = self.get_state()
            notifier(new_state, new_status)

    def get_status(self):
        status = "State: {0}\n\n".format(self.get_state().upper())
        status += self.status
        fault_string = ""
        interlock_string = ""
        if len(self.active_fault_list) > 0:
            fault_string = "\n--------------------------------\nActive FAULTS:\n"
            for fault in self.active_fault_list:
                fault_string += fault
                fault_string += "\n"
        if len(self.active_interlock_list) > 0:
            interlock_string = "\n--------------------------------\nActive INTERLOCKS:\n"
            for interlock in self.active_interlock_list:
                interlock_string += interlock
                interlock_string += "\n"
        final_status_string = status + fault_string + interlock_string
        return final_status_string

    def set_state(self, new_state, shutter_state=None, faults=None, interlocks=None):
        notify_state = False
        if new_state != self.state or shutter_state != self.shutter_state:
            self.state = new_state
            self.shutter_state = shutter_state
            notify_state = True
        if faults != self.active_fault_list or interlocks != self.active_interlock_list:
            self.active_fault_list = faults
            self.active_interlock_list = interlocks
            notify_state = True
        if notify_state is True:
            for notifier in self.state_notifier_list:
                new_status = self.get_status()
                notifier(new_state, new_status)

    def get_state(self):
        return self.state

    def get_shutterstate(self):
        return self.shutter_state

    def add_state_notifier(self, notifier):
        if notifier not in self.state_notifier_list:
            self.state_notifier_list.append(notifier)


if __name__ == "__main__":
    pc = PataraControl("172.16.109.70", 502, 1)
    pc.init_client()
