"""
Created on Aug 02, 2018

@author: Filip Lindau
"""

import threading
import time
import logging
import traceback
from twisted.internet import reactor, defer, error
import PyTango.futures as tangof
from twisted_cut import TangoTwisted
from twisted_cut.TangoTwisted import defer_later
from patara_control import PataraControl
reload(PataraControl)


logger = logging.getLogger("PataraControl")
logger.setLevel(logging.DEBUG)
while len(logger.handlers):
    logger.removeHandler(logger.handlers[0])

# f = logging.Formatter("%(asctime)s - %(module)s.   %(funcName)s - %(levelname)s - %(message)s")
f = logging.Formatter("%(asctime)s - %(name)s.   %(funcName)s - %(levelname)s - %(message)s")
fh = logging.StreamHandler()
fh.setFormatter(f)
logger.addHandler(fh)
logger.setLevel(logging.DEBUG)


class StateDispatcher(object):
    def __init__(self, controller):
        self.controller = controller
        self.stop_flag = False
        self.statehandler_dict = dict()
        self.statehandler_dict[StateUnknown.name] = StateUnknown
        self.statehandler_dict[StateDeviceConnect.name] = StateDeviceConnect
        self.statehandler_dict[StateSetupAttributes.name] = StateSetupAttributes
        self.statehandler_dict[StateStandby.name] = StateStandby
        self.statehandler_dict[StateFault] = StateFault
        self.current_state = StateUnknown.name
        self._state_obj = None
        self._state_thread = None

        self.logger = logging.getLogger("State.StateDispatcher")
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
                state_name = "unknown"
                self.statehandler_dict[StateUnknown.name]
            self.controller.set_state(state_name)
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

    def send_command(self, msg):
        self.logger.info("Sending command {0} to state {1}".format(msg, self.current_state))
        self._state_obj.check_message(msg)

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
        self.logger.setLevel(logging.DEBUG)
        self.deferred_list = list()
        self.next_state = None
        self.cond_obj = threading.Condition()
        self.running = False

    def state_enter(self, prev_state=None):
        self.logger.info("Entering state {0}".format(self.name.upper()))
        with self.cond_obj:
            self.running = True

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

    def send_message(self, msg):
        self.logger.info("Message {0} received".format(msg))
        with self.cond_obj:
            self.cond_obj.notify_all()
            self.check_message(msg)

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
        self.next_state = "device_connect"
        self.stop_run()


class StateDeviceConnect(State):
    """
    Connect to tango devices needed for the frog.
    The names of the devices are stored in the controller.device_names list.
    Devices:
    motor
    spectrometer
    Devices are stored as TangoAttributeFactories in controller.device_factory_dict

    """
    name = "device_connect"

    def __init__(self, controller):
        State.__init__(self, controller)
        self.controller.device_factory_dict = dict()
        self.deferred_list = list()
        # self.logger = logging.getLogger("FrogState.FrogStateDeviceConnect")
        # self.logger.setLevel(logging.DEBUG)
        # self.logger.name = self.name

    def state_enter(self, prev_state):
        State.state_enter(self, prev_state)
        self.controller.set_status("Connecting to Patara device.")
        d = self.controller.init_client()
        d.addCallbacks(self.check_requirements, self.state_error)
        self.deferred_list = [d]

    def check_requirements(self, result):
        self.logger.info("Check requirements result: {0}".format(result))
        self.next_state = "setup_attributes"
        self.stop_run()
        return "setup_attributes"

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
        # Go through all the attributes in the setup_attr_params dict and add
        # do check_attribute with write to each.
        # The deferreds are collected in a list that is added to a DeferredList
        # When the DeferredList fires, the check_requirements method is called
        # as a callback.
        dl = list()
        for key in self.controller.setup_attr_params:
            value = self.controller.setup_attr_params[key]
            self.logger.debug("Setting attribute {0} to {1}".format(key.upper(), value))
            d = self.controller.write_parameter(key, value)
            d.addCallbacks(self.attr_check_cb, self.attr_check_eb)
            dl.append(d)

        # Create DeferredList that will fire when all the attributes are done:
        def_list = defer.DeferredList(dl)
        self.deferred_list.append(def_list)
        def_list.addCallbacks(self.check_requirements, self.state_error)

    def check_requirements(self, result):
        self.logger.info("Check requirements")
        # self.logger.info("Check requirements result: {0}".format(result))
        self.next_state = "idle"
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


class StateStandby(State):
    """
    Wait for time for a new scan or a command. Parameters stored in controller.idle_params
    idle_params["scan_interval"]: time in seconds between scans
    """
    name = "idle"

    def __init__(self, controller):
        State.__init__(self, controller)
        self.t0 = time.time()

    def state_enter(self, prev_state=None):
        State.state_enter(self, prev_state)
        t_delay = self.controller.idle_params["scan_interval"]
        paused = self.controller.idle_params["paused"]
        if paused is False:
            self.logger.debug("Waiting {0} s until starting next scan".format(t_delay))
            self.controller.set_status("Idle. Scan time interval {0} s.".format(t_delay))
            self.t0 = time.time()
            d = defer_later(t_delay, self.check_requirements, ["dummy"])
            # d = defer.Deferred()
        else:
            self.logger.debug("Pausing next scan")
            self.controller.set_status("Idle. Scanning paused.")
            d = defer.Deferred()
        d.addErrback(self.state_error)
        self.deferred_list.append(d)

    def check_requirements(self, result):
        self.logger.info("Check requirements result: {0}".format(result))
        self.next_state = "scan"
        self.stop_run()
        return "scan"

    def state_error(self, err):
        self.logger.error("Error: {0}".format(err))
        if err.type == defer.CancelledError:
            self.logger.info("Cancelled error, ignore")
        else:
            self.controller.set_status("Error: {0}".format(err))
            # If the error was DB_DeviceNotDefined, go to UNKNOWN state and reconnect later
            self.next_state = "unknown"
            self.stop_run()

    def check_message(self, msg):
        if msg == "scan":
            self.logger.debug("Message scan... set next state and stop.")
            self.controller.idle_params["paused"] = False
            d = self.deferred_list[0]   # type: defer.Deferred
            d.cancel()
            self.next_state = "scan"
            self.stop_run()
        elif msg == "analyse":
            self.logger.debug("Message analyse... set next state and stop.")
            d = self.deferred_list[0]   # type: defer.Deferred
            d.cancel()
            self.next_state = "analyse"
            self.stop_run()
        elif msg == "pause":
            self.logger.debug("Message pause")
            d = self.deferred_list[0]   # type: defer.Deferred
            d.cancel()
            self.controller.idle_params["paused"] = True
            self.controller.set_status("Idle. Scanning paused.")


class StateFault(State):
    """
    Handle fault condition.
    """
    name = "fault"

    def __init__(self, controller):
        State.__init__(self, controller)


def test_cb(result):
    logger.debug("Returned {0}".format(result))


def test_err(err):
    logger.error("ERROR Returned {0}".format(err))