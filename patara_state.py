"""
Created on Aug 02, 2018

@author: Filip Lindau
"""

import threading
import time
import logging
import traceback
import PyTango.futures as tangof
from twisted_cut import TangoTwisted
from twisted_cut.TangoTwisted import defer_later
from twisted_cut import defer, error
from patara_control import PataraControl
# reload(PataraControl)


logger = logging.getLogger("PataraState")
while len(logger.handlers):
    logger.removeHandler(logger.handlers[0])

# f = logging.Formatter("%(asctime)s - %(module)s.   %(funcName)s - %(levelname)s - %(message)s")
f = logging.Formatter("%(asctime)s - %(name)s.   %(funcName)s - %(levelname)s - %(message)s")
fh = logging.StreamHandler()
fh.setFormatter(f)
logger.addHandler(fh)
logger.setLevel(logging.INFO)


class StateMessage(object):
    def __init__(self, name, description=None, action_list=None):
        self.name = name
        self.desc = description
        self.action_list = list()
        if action_list is not None:
            self.action_list = action_list

    def add_action(self, f, *args, **kwargs):
        action = (f, args, kwargs)
        self.action_list.append(action)

    def execute_actions(self, *added_args, **added_kwargs):
        for action in self.action_list:
            f = action[0]
            args = action[1]
            args += added_args
            kwargs = dict(action[2])
            kwargs.update(added_kwargs)
            logger.info("Executing {0}: \n {1}({2}, {3})".format(self.name, f, args, kwargs))
            f(*args, **kwargs)


class StateDispatcher(object):
    def __init__(self, controller):
        self.controller = controller
        self.stop_flag = False
        self.statehandler_dict = dict()
        self.statehandler_dict[StateUnknown.name] = StateUnknown
        self.statehandler_dict[StateConnect.name] = StateConnect
        self.statehandler_dict[StateSetupAttributes.name] = StateSetupAttributes
        self.statehandler_dict[StateOff.name] = StateOff
        self.statehandler_dict[StateStandby.name] = StateStandby
        self.statehandler_dict[StateActive.name] = StateActive
        self.statehandler_dict[StateFault.name] = StateFault
        self.current_state = StateUnknown.name
        self._state_obj = None
        self._state_thread = None

        self.logger = logging.getLogger("State.StateDispatcher")
        while len(self.logger.handlers):
            self.logger.removeHandler(self.logger.handlers[0])

        # f = logging.Formatter("%(asctime)s - %(module)s.   %(funcName)s - %(levelname)s - %(message)s")
        f = logging.Formatter("%(asctime)s - %(name)s.   %(funcName)s - %(levelname)s - %(message)s")
        fh = logging.StreamHandler()
        fh.setFormatter(f)
        self.logger.addHandler(fh)
        self.logger.setLevel(logging.DEBUG)

    def statehandler_dispatcher(self):
        self.logger.info("Entering state handler dispatcher")
        prev_state = self.get_state()
        while self.stop_flag is False:
            # Determine which state object to construct:
            try:
                state_name = self.get_state_name()
                self.logger.debug("New state: {0}".format(state_name.upper()))
                self._state_obj = self.statehandler_dict[state_name](self.controller)
            except KeyError:
                self.logger.warning("State {0} not found. Defaulting to UNKNOWN".format(state_name.upper()))
                state_name = "unknown"
                self.statehandler_dict[StateUnknown.name]
            # self.controller.set_state(state_name)
            # Do the state sequence: enter - run - exit
            self._state_obj.state_enter(prev_state)
            self._state_obj.run()       # <- this should be run in a loop in state object and
            # return when it's time to change state
            new_state = self._state_obj.state_exit()
            # Set new state:
            self.set_state(new_state)
            prev_state = state_name
        self._state_thread = None

    def get_state(self):
        return self._state_obj

    def get_state_name(self):
        return self.current_state

    def set_state(self, state_name):
        try:
            self.logger.info("Current state: {0}, set new state {1}".format(self.current_state.upper(),
                                                                            state_name.upper()))
            self.current_state = state_name
        except AttributeError:
            logger.debug("New state unknown. Got {0}, setting to UNKNOWN".format(state_name))
            self.current_state = "unknown"

    def send_command(self, cmd, *data, **kw_data):
        self.logger.info("Sending command {0} to state {1}".format(cmd, self.current_state))
        self._state_obj.check_message(cmd, *data, **kw_data)

    def stop(self):
        self.logger.info("Stop state handler thread")
        self._state_obj.stop_run()
        self.stop_flag = True

    def start(self):
        self.logger.info("Start state handler thread")
        if self._state_thread is not None:
            self.stop()
        self._state_thread = threading.Thread(target=self.statehandler_dispatcher)
        self._state_thread.start()


class State(object):
    name = ""

    def __init__(self, controller):
        self.controller = controller    # type: PataraControl
        self.logger = logging.getLogger("State.{0}".format(self.name.upper()))
        # self.logger.name =
        self.logger.name = self.name
        while len(self.logger.handlers):
            self.logger.removeHandler(self.logger.handlers[0])

        # f = logging.Formatter("%(asctime)s - %(module)s.   %(funcName)s - %(levelname)s - %(message)s")
        f = logging.Formatter("%(asctime)s - %(name)s.   %(funcName)s - %(levelname)s - %(message)s")
        fh = logging.StreamHandler()
        fh.setFormatter(f)
        self.logger.addHandler(fh)
        self.logger.setLevel(logging.INFO)

        self.deferred_list = list()
        self.next_state = None
        self.cond_obj = threading.Condition()
        self.running = False

    def state_enter(self, prev_state=None):
        self.logger.info("Entering state {0}".format(self.name.upper()))
        with self.cond_obj:
            self.running = True
        # self.controller.set_state(self.name)

    def state_exit(self):
        self.logger.info("Exiting state {0}".format(self.name.upper()))
        for d in self.deferred_list:
            try:
                d.cancel()
            except defer.CancelledError:
                pass
        return self.next_state

    def run(self):
        self.logger.info("Entering run, run condition {0}".format(self.running))
        with self.cond_obj:
            if self.running is True:
                self.cond_obj.wait()
        self.logger.debug("Exiting run")

    def check_requirements(self, result):
        """
        If next_state is None: stay on this state, else switch state
        :return:
        """
        self.next_state = None
        return result

    def check_message(self, msg):
        """
        Check message with condition object released and take appropriate action.
        The condition object is released already in the send_message function.

        -- This could be a message queue if needed...

        :param msg:
        :return:
        """
        pass

    def state_error(self, err):
        self.logger.error("Error {0} in state {1}".format(err, self.name.upper()))

    def get_name(self):
        return self.name

    def get_state(self):
        return self.name

    def change_state(self, next_state_name):
        self.next_state = next_state_name
        self.stop_run()

    def send_message(self, msg_name, *msg_args, **msg_kwargs):
        self.logger.info("Message {0} received".format(msg_name))
        with self.cond_obj:
            self.cond_obj.notify_all()
            self.check_message(msg_name, *msg_args, **msg_kwargs)

    def stop_run(self):
        self.logger.info("Notify condition to stop run")
        with self.cond_obj:
            self.running = False
            self.logger.debug("Run condition {0}".format(self.running))
            self.cond_obj.notify_all()


class StateUnknown(State):
    """
    Limbo state.
    Wait and try to connect to devices.
    """
    name = "unknown"

    def __init__(self, controller):
        State.__init__(self, controller)
        self.deferred_list = list()
        self.start_time = None
        self.wait_time = 1.0

    def state_enter(self, prev_state):
        self.logger.info("Starting state {0}".format(self.name.upper()))
        self.controller.set_status("Waiting {0} s before trying to reconnect".format(self.wait_time))
        self.start_time = time.time()
        df = defer_later(self.wait_time, self.check_requirements, [None])
        self.deferred_list.append(df)
        df.addCallback(test_cb)
        self.running = True

    def check_requirements(self, result):
        self.logger.info("Check requirements result {0} for state {1}".format(result, self.name.upper()))
        self.next_state = "connect"
        self.stop_run()


class StateConnect(State):
    """
    Connect to tango devices needed for the frog.
    The names of the devices are stored in the controller.device_names list.
    Devices:
    motor
    spectrometer
    Devices are stored as TangoAttributeFactories in controller.device_factory_dict

    """
    name = "connect"

    def __init__(self, controller):
        State.__init__(self, controller)
        # self.controller.device_factory_dict = dict()
        self.deferred_list = list()
        # self.logger = logging.getLogger("State.StateDeviceConnect")
        self.logger.setLevel(logging.DEBUG)
        # self.logger.name = self.name

    def state_enter(self, prev_state):
        State.state_enter(self, prev_state)
        self.controller.set_status("Connecting to Patara device.")
        d = self.controller.init_client()
        d.addCallbacks(self.check_requirements, self.state_error)
        self.deferred_list = [d]

    def check_requirements(self, result):
        self.logger.info("Check requirements result: {0}".format(result))
        if self.controller.connected is True:
            self.next_state = "setup_attributes"
        else:
            self.next_state = "unknown"
        self.stop_run()
        return self.next_state

    def state_error(self, err):
        self.logger.error("Error: {0}".format(err))
        self.controller.set_status("Error: {0}".format(err))
        # If the error was DB_DeviceNotDefined, go to UNKNOWN state and reconnect later
        self.next_state = "unknown"
        self.stop_run()

    def check_message(self, msg):
        if msg == "disconnect":
            self.logger.debug("Message disconnect... go to unknown.")
            d = self.deferred_list[0]   # type: defer.Deferred
            d.cancel()
            self.next_state = "unknown"
            self.stop_run()


class StateSetupAttributes(State):
    """
    Setup attributes in the tango devices. Parameters stored in controller.setup_attr_params
    Each key in setup_attr_params is a tuple of the form (device_name, attribute_name, value)
    We also want read the wavelength vector for the spectrometer

    Device name is the name of the key in the controller.device_name dict (e.g. "motor", "spectrometer").

    setup_attr_params["speed"]: motor speed
    setup_attr_params["acceleration"]: motor acceleration
    setup_attr_params["exposure"]: spectrometer exposure time
    setup_attr_params["trigger"]: spectrometer use external trigger (true/false)
    setup_attr_params["gain"]: spectrometer gain
    # setup_attr_params["roi"]: spectrometer camera roi (list [top, left, width, height])
    """
    name = "setup_attributes"

    def __init__(self, controller):
        State.__init__(self, controller)
        self.deferred_list = list()

    def state_enter(self, prev_state=None):
        State.state_enter(self, prev_state)
        self.controller.set_status("Setting up device parameters on Patara.")
        self.logger.debug("Setting up device parameters on Patara.")
        # Go through all the attributes in the setup_attr_params dict and add
        # do check_attribute with write to each.
        # The deferreds are collected in a list that is added to a DeferredList
        # When the DeferredList fires, the check_requirements method is called
        # as a callback.
        dl = list()
        for key in self.controller.setup_attr_params:
            value = self.controller.setup_attr_params[key]
            self.logger.debug("Setting attribute {0} to {1}".format(key.upper(), value))
            d = self.controller.write_parameter(key, value, process_now=False, readback=False)
            d.addCallbacks(self.attr_check_cb, self.attr_check_eb)
            dl.append(d)

        if not dl:
            self.logger.debug("Empty list")
        else:
            self.controller.process_queue()
        # Create DeferredList that will fire when all the attributes are done:
        def_list = defer.DeferredList(dl)
        self.deferred_list.append(def_list)
        def_list.addCallbacks(self.check_requirements, self.state_error)

    def check_requirements(self, result=None):
        self.logger.info("Check requirements")
        self.next_state = "standby"
        self.logger.info("Check requirements result: {0}".format(self.next_state))
        self.stop_run()
        return result

    def state_error(self, err):
        self.logger.error("Error: {0}".format(err))
        self.controller.set_status("Error: {0}".format(err))
        # If the error was DB_DeviceNotDefined, go to UNKNOWN state and reconnect later
        self.next_state = "unknown"
        self.stop_run()

    def attr_check_cb(self, result):
        # self.logger.info("Check attribute result: {0}".format(result))
        return result

    def attr_check_eb(self, err):
        self.logger.error("Check attribute ERROR: {0}".format(error))
        return err


class StatePolling(State):
    """
    Parent class for polling state and status of the patara.
    """
    name = ""

    def __init__(self, controller):
        State.__init__(self, controller)
        self.t0 = time.time()
        self.lock = threading.Lock()
        self.deferred_dict = dict()

        self.message_dict = dict()
        self.message_list = list()

        # Fill message dict with content
        msg = StateMessage("connect")
        msg.add_action(self.change_state, "connect")
        self.message_dict[msg.name] = msg

        msg = StateMessage("open")
        msg.add_action(self.controller.write_parameter, "shutter", True, process_now=True, readback=False)
        self.message_dict[msg.name] = msg

        msg = StateMessage("close")
        msg.add_action(self.controller.write_parameter, "shutter", False, process_now=True, readback=False)
        self.message_dict[msg.name] = msg

        msg = StateMessage("start")
        msg.add_action(self.controller.write_parameter, "emission", True, process_now=True, readback=False)
        self.message_dict[msg.name] = msg

        msg = StateMessage("stop")
        msg.add_action(self.controller.write_parameter, "emission", False, process_now=True, readback=False)
        self.message_dict[msg.name] = msg

        msg = StateMessage("clear_fault")
        msg.add_action(self.controller.write_parameter, "clear_fault", True, process_now=True, readback=False)
        self.message_dict[msg.name] = msg

        msg = StateMessage("set_tec_temperature")
        msg.add_action(self.controller.write_parameter, "tec_temp_setting", value=39.2,
                       process_now=True, readback=False)
        self.message_dict[msg.name] = msg

        msg = StateMessage("set_diode_temperature")
        msg.add_action(self.controller.write_parameter, "channel_com1_tec_temp_setting", value=25.0,
                       process_now=True, readback=False)
        self.message_dict[msg.name] = msg

        msg = StateMessage("set_current")
        msg.add_action(self.controller.write_parameter, "channel1_active_current", value=13.4,
                       process_now=True, readback=True)
        self.message_dict[msg.name] = msg

    def state_enter(self, prev_state=None):
        """
        Entering standby state.

        Conditions:
        Shutter is closed.
        Emission is on

        Read all parameters initially.
        Startup periodic polling of parameters.

        :param prev_state:
        :return:
        """
        State.state_enter(self, prev_state)

        self.controller.set_status("")

        # Init polling
        with self.lock:
            d = self.controller.read_control_state(False)
            d.addCallback(self.poll_control_state)
            d.addErrback(self.state_error)
            self.deferred_dict["control"] = d
            self.deferred_list.append(d)

            d = self.controller.read_status(False)
            d.addCallback(self.poll_status)
            d.addErrback(self.state_error)
            self.deferred_dict["status"] = d
            self.deferred_list.append(d)

            d = self.controller.read_input_registers(True, range_id=0)
            d.addCallback(self.poll_input_registers)
            d.addErrback(self.state_error)
            self.deferred_dict["input"] = d
            self.deferred_list.append(d)

    def check_requirements(self, result):
        self.logger.debug("Check requirements result: {0}".format(result))

        patara_state = self.controller.get_state()
        if patara_state == "standby_state":
            state_name = "standby"
        elif patara_state in ["active_state", "pre-fire_state"]:
            state_name = "active"
        elif patara_state == "off_state":
            state_name = "off"
        elif patara_state == "fault_state":
            state_name = "fault"
        else:
            state_name = "unknown"

        if state_name != self.name:
            self.next_state = state_name
            self.stop_run()
            retval = self.next_state
        else:
            retval = self.name
        return retval

    def state_error(self, err):
        self.logger.error("Error: {0}".format(err))
        self.logger.error("Type: {0}".format(err.type))
        if err.type == defer.CancelledError:
            self.logger.info("Cancelled error, ignore")
        else:
            self.logger.info("Not cancelled error, switch to unknown")
            self.controller.set_status("Error: {0}".format(err))
            # If the error was DB_DeviceNotDefined, go to UNKNOWN state and reconnect later
            self.next_state = "unknown"
            self.stop_run()

    def check_message(self, msg_name, *msg_args, **msg_kwargs):
        """

        :param msg_name:
        :param msg_args:
        :param msg_kwargs:
        :return:
        """
        if msg_name in self.message_list:
            self.logger.info("Message in list. Executing")
            self.logger.info("{0}, args: {1}, kwargs: {2}".format(msg_name, msg_args, msg_kwargs))
            self.message_dict[msg_name].execute_actions(*msg_args, **msg_kwargs)
        else:
            self.logger.info("Message NOT in list.")

    def send_message(self, msg_name, *msg_args, **msg_kwargs):
        self.logger.info("Message {0} received".format(msg_name))
        with self.cond_obj:
            self.cond_obj.notify_all()
            self.check_message(msg_name, *msg_args, **msg_kwargs)

    def poll_control_state(self, result):
        """
        Queues up a new poll control state of the Patara after a time interval
        stored in controller.standby_polling_attrs["control"].

        Contains emission, shutter, clear fault etc.

        :param result: Deferred result
        :return:
        """
        self.logger.debug("Result: {0}".format(result))
        with self.lock:
            t = self.controller.standby_polling_attrs["control"]
            d = defer_later(t, self.controller.read_control_state, True)
            d.addCallback(self.cb_control_state)
            d.addErrback(self.state_error)

            old_d = self.deferred_dict["control"]
            try:
                self.deferred_list.remove(old_d)
            except ValueError:
                self.logger.debug("Deferred not in deferred_list")

            self.deferred_dict["control"] = d
            self.deferred_list.append(d)

    def cb_control_state(self, result):
        """
        Callback for control state poll. Checks if the state has changed.

        :param result:
        :return:
        """

        self.logger.debug("Result: {0}".format(result))
        old_d = self.deferred_dict["control"]
        try:
            self.deferred_list.remove(old_d)
        except ValueError:
            self.logger.debug("Deferred not in deferred_list")

        if isinstance(result, defer.Deferred):
            d = result
            d.addCallback(self.poll_control_state)
            d.addErrback(self.state_error)
            self.deferred_dict["control"] = d
            self.deferred_list.append(d)
        else:
            self.poll_control_state(None)

    def poll_input_registers(self, result):
        """
        Queues up a new poll input registers of the Patara after a time interval
        stored in controller.standby_polling_attrs["status"].

        Contains current, temperatures, shot counter ...

        :param result: Deferred result
        :return:
        """
        self.logger.debug("Result: {0}".format(result))
        with self.lock:
            t = self.controller.standby_polling_attrs["input_registers"]
            d = defer_later(t, self.controller.read_input_registers, True)
            d.addCallback(self.cb_input_registers)
            d.addErrback(self.state_error)

            old_d = self.deferred_dict["input"]
            try:
                self.deferred_list.remove(old_d)
            except ValueError:
                self.logger.debug("Deferred not in deferred_list")

            self.deferred_dict["input"] = d
            self.deferred_list.append(d)

    def cb_input_registers(self, result):
        """
        Callback for input registers poll. Checks if the state has changed.

        :param result:
        :return:
        """

        self.logger.debug("Type result: {0}".format(type(result)))
        self.logger.debug("Result: {0}".format(result))

        old_d = self.deferred_dict["input"]
        try:
            self.deferred_list.remove(old_d)
        except ValueError:
            self.logger.debug("Deferred not in deferred_list")

        if isinstance(result, defer.Deferred):
            d = result
            d.addCallback(self.poll_input_registers)
            d.addErrback(self.state_error)
            self.deferred_dict["input"] = d
            self.deferred_list.append(d)
        else:
            self.poll_input_registers(None)

    def poll_status(self, result):
        """
        Queues up a new poll status of the Patara after a time interval
        stored in controller.standby_polling_attrs["status"].

        Contains state, faults, interlocks

        :param result: Deferred result
        :return:
        """
        self.logger.debug("Result: {0}".format(result))
        with self.lock:
            t = self.controller.standby_polling_attrs["status"]
            d = defer_later(t, self.controller.read_status, True)
            d.addCallback(self.cb_status)
            d.addErrback(self.state_error)

            old_d = self.deferred_dict["status"]
            try:
                self.deferred_list.remove(old_d)
            except ValueError:
                self.logger.debug("Deferred not in deferred_list")

            self.deferred_dict["status"] = d
            self.deferred_list.append(d)

    def cb_status(self, result):
        """
        Callback for status poll. Checks if the state has changed.

        :param result:
        :return:
        """
        old_d = self.deferred_dict["status"]
        try:
            self.deferred_list.remove(old_d)
        except ValueError:
            self.logger.debug("Deferred not in deferred_list")

        # Check if the state has changed:
        self.check_requirements(result)

        self.logger.debug("Status result: {0}".format(result))
        self.poll_status(None)
        return result


class StateOff(StatePolling):
    """
    Handle fault condition.
    """
    name = "off"

    def __init__(self, controller):
        StatePolling.__init__(self, controller)
        self.t0 = time.time()
        self.lock = threading.Lock()
        self.deferred_dict = dict()
        self.message_list = ["open", "close", "connect", "set_tec_temperature", "set_current",
                             "start", "stop", "clear_fault"]

    def state_enter(self, prev_state=None):
        """
        Entering standby state.

        Conditions:
        Shutter is closed.
        Emission is on

        Read all parameters initially.
        Startup periodic polling of parameters.

        :param prev_state:
        :return:
        """
        StatePolling.state_enter(self, prev_state)

        self.controller.set_status("Laser OFF. Emission OFF. Shutter CLOSED. Temperature control active.")

    def check_requirements(self, result):
        StatePolling.check_requirements(self, result)

    def state_error(self, err):
        StatePolling.state_error(self, err)


class StateStandby(StatePolling):
    """
    Wait while polling state and status of the patara.
    """
    name = "standby"

    def __init__(self, controller):
        StatePolling.__init__(self, controller)
        self.t0 = time.time()
        self.lock = threading.Lock()
        self.deferred_dict = dict()
        self.message_list = ["open", "close", "connect", "set_tec_temperature", "set_current",
                             "start", "stop", "clear_fault"]

    def state_enter(self, prev_state=None):
        """
        Entering standby state.

        Conditions:
        Shutter is closed.
        Emission is on

        Read all parameters initially.
        Startup periodic polling of parameters.

        :param prev_state:
        :return:
        """
        StatePolling.state_enter(self, prev_state)

        self.controller.set_status("Laser STANDBY. Emission ON. Shutter CLOSED. Temperature control active.")

    def check_requirements(self, result):
        StatePolling.check_requirements(self, result)

    def state_error(self, err):
        StatePolling.state_error(self, err)


class StateActive(StatePolling):
    """
    Wait while polling state and status of the patara.
    """
    name = "active"

    def __init__(self, controller):
        StatePolling.__init__(self, controller)
        self.t0 = time.time()
        self.lock = threading.Lock()
        self.deferred_dict = dict()
        self.message_list = ["open", "close", "connect", "set_tec_temperature", "set_current",
                             "start", "stop", "clear_fault"]

    def state_enter(self, prev_state=None):
        """
        Entering standby state.

        Conditions:
        Shutter is closed.
        Emission is on

        Read all parameters initially.
        Startup periodic polling of parameters.

        :param prev_state:
        :return:
        """
        StatePolling.state_enter(self, prev_state)

        self.controller.set_status("Laser ACTIVE. Emission ON. Shutter OPEN. Temperature control active.")

    def check_requirements(self, result):
        StatePolling.check_requirements(self, result)

    def state_error(self, err):
        StatePolling.state_error(self, err)


class StateFault(StatePolling):
    """
    Handle fault condition.
    """
    name = "fault"

    def __init__(self, controller):
        StatePolling.__init__(self, controller)
        self.t0 = time.time()
        self.lock = threading.Lock()
        self.deferred_dict = dict()
        self.message_list = ["open", "close", "connect", "set_tec_temperature", "set_current",
                             "start", "stop", "clear_fault"]

    def state_enter(self, prev_state=None):
        """
        Entering standby state.

        Conditions:
        Shutter is closed.
        Emission is on

        Read all parameters initially.
        Startup periodic polling of parameters.

        :param prev_state:
        :return:
        """
        StatePolling.state_enter(self, prev_state)

        self.controller.set_status("Laser FAULT.")

    def check_requirements(self, result):
        StatePolling.check_requirements(self, result)

    def state_error(self, err):
        StatePolling.state_error(self, err)


def test_cb(result):
    logger.debug("Returned {0}".format(result))


def test_err(err):
    logger.error("ERROR Returned {0}".format(err))
