"""
Created on Aug 02, 2018

@author: Filip Lindau
"""

from twisted_cut import defer, TangoTwisted
import logging
import time
import numpy as np
from PyTango.server import Device, DeviceMeta
from PyTango.server import attribute, command
from PyTango.server import device_property
import PyTango as pt
from patara_control import PataraControl
from patara_state import StateDispatcher

# logger = logging.getLogger("PataraControl")
# while len(logger.handlers):
#     logger.removeHandler(logger.handlers[0])
#
# f = logging.Formatter("%(asctime)s - %(name)s.   %(funcName)s - %(levelname)s - %(message)s")
# fh = logging.StreamHandler()
# fh.setFormatter(f)
# logger.addHandler(fh)
# logger.setLevel(logging.WARNING)


class PataraDS(Device):
    __metaclass__ = DeviceMeta

    # --- Expert attributes
    #
    # warranty_timer = attribute(label='warranty_timer',
    #                            dtype=float,
    #                            access=pt.AttrWriteType.READ,
    #                            display_level=pt.DispLevel.EXPERT,
    #                            unit="h",
    #                            format="%8.1f",
    #                            min_value=0.0,
    #                            max_value=100000.0,
    #                            fget="get_warranty_timer",
    #                            doc="Number of hours accumulated on the warranty timer", )

    # --- Operator attributes
    #
    current = attribute(label='current',
                        dtype=float,
                        access=pt.AttrWriteType.READ,
                        unit="A",
                        format="%6.2f",
                        min_value=0.0,
                        max_value=30.0,
                        fget="get_current",
                        doc="Diode current", )

    voltage = attribute(label='voltage',
                        dtype=float,
                        access=pt.AttrWriteType.READ,
                        unit="V",
                        format="%6.2f",
                        min_value=0.0,
                        max_value=100.0,
                        fget="get_voltage",
                        doc="Diode voltage", )

    shutter = attribute(label='shutter',
                        dtype=bool,
                        access=pt.AttrWriteType.READ,
                        unit="",
                        format="%6.2f",
                        fget="get_shutter",
                        doc="Shutter status open/close", )

    humidity = attribute(label='humidity',
                         dtype=float,
                         access=pt.AttrWriteType.READ,
                         unit="%",
                         format="%6.2f",
                         min_value=0.0,
                         max_value=100.0,
                         fget="get_humidity",
                         doc="Laser enclosure humidity", )

    shot_counter = attribute(label='shot counter',
                             dtype=np.int64,
                             access=pt.AttrWriteType.READ,
                             unit="%",
                             format="%6.2f",
                             min_value=0,
                             max_value=4294967296,
                             fget="get_shotcounter",
                             doc="Shot counter", )

    # --- Device properties
    #
    ip_address = device_property(dtype=str,
                                 doc="IP address for the Patara",
                                 default_value="172.16.109.70")

    port = device_property(dtype=int,
                           doc="Modbus port",
                           default_value=502)

    slave_id = device_property(dtype=int,
                               doc="Device id",
                               default_value=1)

    def __init__(self, klass, name):
        self.controller = None              # type: PataraControl
        self.setup_attr_params = dict()
        self.idle_params = dict()
        self.scan_params = dict()
        self.analyse_params = dict()
        self.db = None
        self.state_dispatcher = None    # type: FrogStateDispatcher
        Device.__init__(self, klass, name)

    def init_device(self):
        self.debug_stream("In init_device:")
        Device.init_device(self)
        self.db = pt.Database()
        self.set_state(pt.DevState.UNKNOWN)
        try:
            if self.state_dispatcher is not None:
                self.state_dispatcher.stop()
        except Exception as e:
            self.error_info("Error stopping state dispatcher: {0}".format(e))
        try:
            self.controller = PataraControl(self.ip_address, self.port, self.slave_id)
            self.controller.add_state_notifier(self.change_state)
        except Exception as e:
            self.error_stream("Error creating Patara controller: {0}".format(e))
            return

        self.setup_params()

        self.state_dispatcher = StateDispatcher(self.controller)
        self.state_dispatcher.start()

        self.debug_stream("init_device finished")
        # self.set_state(pt.DevState.ON)

    def change_state(self, new_state, new_status):
        self.info_stream("New state: {0}".format(new_state))
        if new_state in ["off_state"]:
            tg_state = pt.DevState.OFF
        elif new_state in ["standby_state"]:
            tg_state = pt.DevState.STANDBY
        elif new_state in ["active_state", "pre-fire_state"]:
            if self.controller.get_shutterstate() is True:
                tg_state = pt.DevState.RUNNING
            else:
                tg_state = pt.DevState.ON
        elif new_state in ["fault_state"]:
            tg_state = pt.DevState.FAULT
        else:
            tg_state = pt.DevState.UNKNOWN
        self.set_state(tg_state)

        if new_status is not None:
            self.set_status(new_status)

    def setup_params(self):
        pass

    def get_current(self):
        p = self.controller.get_parameter("channel1_sensed_current_flow")
        if p is None:
            value = None
            t = None
            q = pt.AttrQuality.ATTR_INVALID
        else:
            value = p.value
            t = p.timestamp
            if value is not None:
                q = pt.AttrQuality.ATTR_VALID
            else:
                q = pt.AttrQuality.ATTR_VALID
        return value, t, q

    def get_shutter(self):
        p = self.controller.get_parameter("shutter")
        if p is None:
            value = None
            t = None
            q = pt.AttrQuality.ATTR_INVALID
        else:
            value = p.value
            t = p.timestamp
            if value is not None:
                q = pt.AttrQuality.ATTR_VALID
            else:
                q = pt.AttrQuality.ATTR_VALID
        return value, t, q

    def get_voltage(self):
        p = self.controller.get_parameter("channel1_power_supply_voltage")
        if p is None:
            value = None
            t = None
            q = pt.AttrQuality.ATTR_INVALID
        else:
            value = p.value
            t = p.timestamp
            if value is not None:
                q = pt.AttrQuality.ATTR_VALID
            else:
                q = pt.AttrQuality.ATTR_VALID
        return value, t, q

    def get_humidity(self):
        p = self.controller.get_parameter("humidity_reading")
        if p is None:
            value = None
            t = None
            q = pt.AttrQuality.ATTR_INVALID
        else:
            value = p.value
            t = p.timestamp
            if value is not None:
                q = pt.AttrQuality.ATTR_VALID
            else:
                q = pt.AttrQuality.ATTR_VALID
        return value, t, q

    def get_shotcounter(self):
        p = self.controller.get_parameter("channel1_pulsed_mode_shot_counter_low")
        if p is None:
            value_low = None
            t = None
            q_low = pt.AttrQuality.ATTR_INVALID
        else:
            value_low = p.value
            t = p.timestamp
            if value_low is not None:
                q_low = pt.AttrQuality.ATTR_VALID
            else:
                q_low = pt.AttrQuality.ATTR_VALID

        p = self.controller.get_parameter("channel1_pulsed_mode_shot_counter_high")
        if p is None:
            value_high = None
            t = None
            q_high = pt.AttrQuality.ATTR_INVALID
        else:
            value_high = p.value
            t = p.timestamp
            if value_high is not None:
                q_high = pt.AttrQuality.ATTR_VALID
            else:
                q_high = pt.AttrQuality.ATTR_VALID

        if q_high is pt.AttrQuality.ATTR_VALID and q_low is pt.AttrQuality.ATTR_VALID:
            q = pt.AttrQuality.ATTR_VALID
            value = value_high * 65536 + value_low
        else:
            q = pt.AttrQuality.ATTR_INVALID
            value = None

        return value, t, q

    def delete_device(self):
        self.info_stream("In delete_device: closing connection to patara")
        self.controller.close_client()


if __name__ == "__main__":
    pt.server.server_run((PataraDS, ))
