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

logger = logging.getLogger("PataraControl")
logger.setLevel(logging.DEBUG)
while len(logger.handlers):
    logger.removeHandler(logger.handlers[0])

f = logging.Formatter("%(asctime)s - %(name)s.   %(funcName)s - %(levelname)s - %(message)s")
fh = logging.StreamHandler()
fh.setFormatter(f)
logger.addHandler(fh)
logger.setLevel(logging.DEBUG)


class PataraDS(Device):
    __metaclass__ = DeviceMeta

    # --- Expert attributes
    #
    dt = attribute(label='warranty_timer',
                   dtype=float,
                   access=pt.AttrWriteType.READ,
                   display_level=pt.DispLevel.EXPERT,
                   unit="h",
                   format="%4.2e",
                   min_value=0.0,
                   max_value=100000.0,
                   fget="get_warranty_timer",
                   doc="Number of hours accumulated on the warranty timer", )

    # --- Operator attributes
    #
    delta_t = attribute(label='delta_t',
                        dtype=float,
                        access=pt.AttrWriteType.READ,
                        unit="s",
                        format="%3.2e",
                        min_value=0.0,
                        max_value=1.0,
                        fget="get_delta_t",
                        doc="Reconstructed pulse time intensity FWHM", )

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
            self.controller = PataraControl(self.spectrometer_name, self.motor_name)
            self.controller.add_state_notifier(self.change_state)
        except Exception as e:
            self.error_stream("Error creating camera controller: {0}".format(e))
            return

        self.setup_params()

        self.state_dispatcher = FrogStateDispatcher(self.controller)
        self.state_dispatcher.start()

        self.debug_stream("init_device finished")
        # self.set_state(pt.DevState.ON)