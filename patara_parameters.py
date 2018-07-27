"""
Created on Jul 25, 2018

@author: Filip Lindau
"""
import time


class PataraError(Exception):
    pass


class PataraParameter(object):
    """
    Stores a parameter. Identified by name. Optional read_rate can be used to indicate
    how often the parameter should be updated. Read rate = -1.0 indicates read when written.
    New values are stored from raw values and converted to actual values by means of
    a conversion factor and optional offset.
    """

    def __init__(self, name, address, func, conversion_factor=1.0, read_rate=-1.0, desc=None):
        """

        :param name: Parameter name
        :param address: Modbus address
        :param func: Modbus function (1=coil, 2=discrete input, 3=holding register, 4=input register)
        :param conversion_factor:
        :param read_rate:
        :param desc: Description string
        """
        self.name = name
        self.factor = conversion_factor
        self.offset = 0.0
        self.read_rate = read_rate
        self.timestamp = None
        self.value = None
        self.raw_value = None
        self.desc = desc
        self.function = func
        self.address = address

    def get_name(self):
        return self.name

    def get_timestamp(self):
        return self.timestamp

    def set_value(self, raw_value, timestamp=None):
        self.raw_value = raw_value
        self.value = self.factor * self.raw_value + self.offset
        if timestamp is None:
            self.timestamp = time.time()
        else:
            self.timestamp = timestamp

    def get_value(self):
        return self.value

    def set_conversion(self, factor, offset):
        self.factor = factor
        self.offset = offset

    def get_conversion(self):
        return self.factor, self.offset

    def set_readrate(self, read_rate):
        self.read_rate = read_rate

    def get_readrate(self):
        return self.read_rate

    def set_description(self, desc):
        self.desc = desc

    def get_description(self):
        return self.desc

    def __eq__(self, other):
        return self.name == other

    def __ne__(self, other):
        return self.name != other

    def __str__(self):
        s = "Parameter {0}: {1}\nCurrent value: {2}".format(self.name, self.desc, self.value)
        return s


class PataraHardwareParameters(object):
    """
    Parameters stored in this class is in system units. They are for internal
    representation only. To get useful units use getXX function in parent class.
    """

    def __init__(self):
        self.parameters = dict()
        self.coil_table = dict()
        self.coil_read_range = None
        self.discrete_input_table = dict()
        self.discrete_input_read_range = None
        self.input_register_table = dict()
        self.input_register_read_range = None
        self.holding_register_table = dict()
        self.holding_register_read_range = None

        self.init_coils()
        self.init_discrete()
        self.init_holding_registers()
        self.init_input_registers()

    def init_coils(self):
        # Function 01: Read/write bits
        name = "emission"
        desc = "Laser emission state"
        addr = 0
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "enable_standby"
        desc = "Standby state, Commanding emission to OFF will reset this bit"
        addr = 1
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "external_trigger"
        desc = "OFF = The eDrive will run on internal triggering from the Timing Engine, " \
               "ON = The eDrive will run on external triggering using the Trigger/Gate input"
        addr = 2
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "internal_trigger_gating"
        desc = "OFF = The internal trigger is free-running, " \
               "ON = The Trigger/Gate input will be used to gate the internally generated trigger pulses"
        addr = 3
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "shutter"
        desc = "OFF = The shutter is always closed, " \
               "ON = The shutter opens when emission is active"
        addr = 4
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "clear_fault"
        desc = "Set this bit to clear existing eDrive faults."
        addr = 5
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "qsv_enable"
        desc = "OFF = RF AO Q-switch driver is disabled, ON = RF AO Q-switch driver is enabled"
        addr = 6
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "fps_enable"
        desc = "OFF = Q-switch FPS is disabled, ON = Q-switch FPS is enabled"
        addr = 7
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "fps_ppk_enable"
        desc = "OFF = Q-switch FPS PPK is disabled, ON = Q-switch FPS PPK is enabled"
        addr = 8
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "shutter_fps_enable"
        desc = "OFF = Shutter FPS is disabled, ON = Shutter FPS is enabled"
        addr = 9
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "marking_mode_trigger"
        desc = "OFF = Marking mode trigger coil is disabled, ON = Marking mode trigger coil is enabled"
        addr = 10
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "front_panel_locked_out"
        desc = "OFF = Front panel access is locked out, ON = Front panel access is unlocked"
        addr = 11
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "tec_enable"
        desc = "Available only in manufacturing mode"
        addr = 12
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "channel1_enable"
        desc = "OFF = Channel 1 AIM is disabled, ON = Channel 1 AIM is enabled"
        addr = 16
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "channel1_mode"
        desc = "OFF = QCW (pulsed) operation is selected, ON = CW operation is selected," \
               "Note: This bit can only be changed when the eDrive is not active and Channel 1 " \
               "is disabled on models equipped with QCW only."
        addr = 17
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "channel1_ramp_control"
        desc = "OFF = Disable current ramping for Channel 1, ON = Enable current ramping for Channel 1"
        addr = 18
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "channel1_slew_rate_control"
        desc = "OFF = Slew rate control is disabled, ON = Slew rate control is enabled"
        addr = 19
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "channel_com0_enable"
        desc = "OFF = COM0 AIM is disabled, ON = COM0 AIM is enabled"
        addr = 40
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "channel_com0_slew_enable"
        desc = "OFF = Slew rate control is disabled, ON = Slew rate control is enabled"
        addr = 41
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "channel_com0_tec_enable"
        desc = "OFF = TEC on COM0 is disabled, ON = TEC on COM0 is enabled"
        addr = 42
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "channel_com1_enable"
        desc = "OFF = COM1 AIM is disabled, ON = COM1 AIM is enabled"
        addr = 48
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "channel_com1_slew_enable"
        desc = "OFF = Slew rate control is disabled, ON = Slew rate control is enabled"
        addr = 49
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        name = "channel_com1_tec_enable"
        desc = "OFF = TEC on COM1 is disabled, ON = TEC on COM1 is enabled"
        addr = 50
        self.coil_table[addr] = name
        self.parameters[name] = PataraParameter(name, address=addr, func=1, read_rate=3.0, desc=desc)

        self.coil_read_range = [(0, 4, 3.0), (5, 50, -1.0)]

    def init_discrete(self):
        # Function 02: Read bits
        name = "fault_state"
        desc = "OFF = The eDrive is not in the fault state, ON = The eDrive is in the fault state"
        addr = 0
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "off_state"
        desc = ""
        addr = 1
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "standby_state"
        desc = ""
        addr = 2
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "pre-fire_state"
        desc = ""
        addr = 3
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "active_state"
        desc = ""
        addr = 4
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_present"
        desc = ""
        addr = 5
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel2_present"
        desc = ""
        addr = 6
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel3_present"
        desc = ""
        addr = 7
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "chiller_flow_fault"
        desc = ""
        addr = 8
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "chiller_level_fault"
        desc = ""
        addr = 9
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "emergency_stop_fault"
        desc = ""
        addr = 10
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "q-switch_fault"
        desc = ""
        addr = 11
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_fault"
        desc = ""
        addr = 12
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel2_fault"
        desc = ""
        addr = 13
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel3_fault"
        desc = ""
        addr = 14
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "front_panel_fault"
        desc = ""
        addr = 15
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "laser_cover_interlock"
        desc = "OFF = The laser cover interlock is grounded, ON = The laser cover interlock is open"
        addr = 16
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "laser_coolant_flow_interlock"
        desc = "OFF = The laser system coolant flow interlock is grounded, " \
               "ON = The laser system coolant flow interlock is open"
        addr = 17
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "q-switch_thermal_interlock"
        desc = "OFF = The Q-switch thermal interlock is grounded, ON = The Q-switch thermal interlock is open"
        addr = 18
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "q-switch_driver_thermal_fault"
        desc = ""
        addr = 19
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "q-switch_crystal_thermal_interlock"
        desc = "OFF = The Q-switch thermal BNC interlock is shorted (safe), " \
               "ON = The Q-switch thermal BNC interlock is open (faulted)"
        addr = 20
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "q-switch_hvswr_fault"
        desc = ""
        addr = 21
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "q-switch_high_power_fault"
        desc = ""
        addr = 22
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "laser_shutter_state"
        desc = "OFF = The shutter output is not energized, ON = The shutter output is energized"
        addr = 23
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "tec_present"
        desc = ""
        addr = 24
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "tec_fault"
        desc = ""
        addr = 25
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "tec_tolerance_fault"
        desc = ""
        addr = 26
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "tec_comm_fault"
        desc = ""
        addr = 27
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "shutter_interlock_fault"
        desc = ""
        addr = 28
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "tec_open_rtd_fault"
        desc = ""
        addr = 29
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "tec_over_heat_fault"
        desc = ""
        addr = 30
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "tec_under_voltage_fault"
        desc = ""
        addr = 31
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_off_state"
        desc = ""
        addr = 32
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_standby"
        desc = ""
        addr = 33
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_active"
        desc = ""
        addr = 34
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_fault_state"
        desc = ""
        addr = 35
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_state_mismatch_fault"
        desc = ""
        addr = 36
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_comm_fault"
        desc = ""
        addr = 37
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_hardware_fault"
        desc = ""
        addr = 38
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_e-stop_fault"
        desc = ""
        addr = 39
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_comm_timeout_fault"
        desc = ""
        addr = 40
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_interlock_fault"
        desc = ""
        addr = 41
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_temp_fault"
        desc = ""
        addr = 42
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_overcurrent_fault"
        desc = ""
        addr = 43
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_low_voltage_fault"
        desc = ""
        addr = 44
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "channel1_current_tolerance_fault"
        desc = ""
        addr = 45
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_off_state"
        desc = ""
        addr = 80
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_standby_state"
        desc = ""
        addr = 81
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_active_state"
        desc = ""
        addr = 82
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_fault_state"
        desc = ""
        addr = 83
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_comm_fault"
        desc = ""
        addr = 84
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_hardware_fault"
        desc = ""
        addr = 85
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_temp_fault"
        desc = ""
        addr = 86
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_tec_fault"
        desc = ""
        addr = 87
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_tec_comm_fault"
        desc = ""
        addr = 88
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_tec_tolerance_fault"
        desc = ""
        addr = 89
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        name = "comm0_tec_open_rtd_fault"
        desc = ""
        addr = 91
        self.parameters[name] = PataraParameter(name, address=addr, func=2, read_rate=3.0, desc=desc)

        self.discrete_input_read_range = [(0, 91, 3.0)]

    def init_holding_registers(self):
        # Function 03: Read/write registers
        name = "system_frequency"
        desc = "This value represents the frequency of the internal timing engine. " \
               "If Channel 1 is in CW mode, this frequency is only used for Q-switch pulse generation. " \
               "If Channel 1 is in QCW mode, this frequency is used for pulsing of Channel 1 " \
               "and the Q-switch pulses are tied to the current pulse. Range: 2 to 50,000. LSB value: 1 Hz"
        addr = 0
        self.parameters[name] = PataraParameter(name, address=addr, func=3, read_rate=-1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "trigger_out_config"
        desc = "0 = Trigger out mimics QSW HIGH pulse, 1 = Trigger out mimics QSW HIGH pulse, " \
               "2 = Trigger out sync on leading current pulse"
        addr = 10
        self.parameters[name] = PataraParameter(name, address=addr, func=3, read_rate=-1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "shutter_delay"
        desc = "Range: 0 μs to 500 ms. LSB value: 1 μs"
        addr = 14
        self.parameters[name] = PataraParameter(name, address=addr, func=3, read_rate=-1.0,
                                                conversion_factor=1.0e-6, desc=desc)

        name = "channel1_active_current"
        desc = "Measured in amperes (A), this value represents the current level for Channel 1 " \
               "when the eDrive is actively driving the array output in either CW or QCW modes. " \
               "See standby current below. Range: 0 to 1,000. LSB value: 0.1 A"
        addr = 16
        self.parameters[name] = PataraParameter(name, address=addr, func=3, read_rate=-1.0,
                                                conversion_factor=0.1, desc=desc)

        name = "channel1_standby_current"
        desc = "Measured in amperes (A), this value represents the current level for Channel 1 " \
               "when the eDrive is in standby CW or QCW mode or during the inactive portion of the QCW pulse. " \
               "Range: 0 to 1,000. LSB value: 0.1 A"
        addr = 17
        self.parameters[name] = PataraParameter(name, address=addr, func=3, read_rate=-1.0,
                                                conversion_factor=0.1, desc=desc)

        name = "tec_temp_setting"
        desc = "This value represents the TEC temperature setting of the internal TEC. " \
               "Range: -40.0 degC to 150.0 degC. LSB value: 0.1 degC"
        addr = 88
        self.parameters[name] = PataraParameter(name, address=addr, func=3, read_rate=-1.0,
                                                conversion_factor=0.1, desc=desc)

        name = "com0_tec_temp_setting"
        desc = "This value represents the TEC temperature setting of the COM0 TEC. " \
               "Range: -40.0 degC to 150.0 degC. LSB value: 0.1 degC"
        addr = 104
        self.parameters[name] = PataraParameter(name, address=addr, func=3, read_rate=-1.0,
                                                conversion_factor=0.1, desc=desc)

        self.holding_register_read_range = [(0, 17, -1.0), (88, 104, -1.0)]

    def init_input_registers(self):
        name = "sc_firmware_version_x"
        desc = ""
        addr = 0
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=-1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "sc_firmware_version_y"
        desc = ""
        addr = 1
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=-1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "sc_firmware_version_z"
        desc = ""
        addr = 2
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=-1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "channel1_firmware_version_x"
        desc = ""
        addr = 16
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=-1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "channel1_firmware_version_y"
        desc = ""
        addr = 17
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=-1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "channel1_firmware_version_z"
        desc = ""
        addr = 18
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=-1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "channel1_sensed_current_flow"
        desc = "This value represents the amount of current presently flowing through Channel 1. " \
               "If the eDrive is in pulsed mode and active, the current reading during the active pulse " \
               "will be returned. Range: 0 to 1,000. LSB value: 0.1 A"
        addr = 19
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=2.0,
                                                conversion_factor=0.1, desc=desc)

        name = "channel1_power_supply_voltage"
        desc = "This value represents the power supply voltage reading for Channel 1. " \
               "Range: 0 to 3,500. LSB value: 0.1 V"
        addr = 20
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=1.0,
                                                conversion_factor=0.1, desc=desc)

        name = "channel1_temperature"
        desc = "This value represents the temperature reading for Channel 1. " \
               "Range: 0 degC to 1,000 degC. LSB value: 0.1 degC"
        addr = 21
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=2.0,
                                                conversion_factor=0.1, desc=desc)

        name = "channel1_current_limit"
        desc = "This value represents the current limit setting for Channel 1. " \
               "Range: 0 to 1,000. LSB value: 0.1 A"
        addr = 22
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=-1.0,
                                                conversion_factor=0.1, desc=desc)

        name = "channel1_warranty_timer_high"
        desc = "This value represents the high word of the number of hours accumulated on the warranty timer " \
               "of the Channel 1 AIM. Range: 0 to 4,294,967,295. LSB value: 1 s"
        addr = 24
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "channel1_warranty_timer_low"
        desc = "This value represents the low word of the number of hours accumulated on the warranty timer " \
               "of the Channel 1 AIM. Range: 0 to 4,294,967,295. LSB value: 1 s"
        addr = 25
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "channel1_pulsed_mode_shot_counter_high"
        desc = "This value represents the Channel 1 shot counter high word. Range: 0 to 4,294,967,295"
        addr = 30
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=2.0,
                                                conversion_factor=1.0, desc=desc)

        name = "channel1_pulsed_mode_shot_counter_low"
        desc = "This value represents the Channel 1 shot counter low word. Range: 0 to 4,294,967,295"
        addr = 31
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=2.0,
                                                conversion_factor=1.0, desc=desc)

        name = "humidity_reading"
        desc = "This value represents the humidity reading. Range: 0 to 100. LSB value: 1 percent humidity"
        addr = 33
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=1.0,
                                                conversion_factor=1.0, desc=desc)

        name = "channel_com0_sensed_current"
        desc = "Current from COM0 AIM in 0.1 A increments."
        addr = 112
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=1.0,
                                                conversion_factor=0.1, desc=desc)

        name = "channel_com0_sensed_temp"
        desc = "This value represents the temperature reading for the COM0 TEC. " \
               "Range: 0 degC to 1,000 degC. LSB value: 0.1 degC"
        addr = 115
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=1.0,
                                                conversion_factor=0.1, desc=desc)

        name = "channel_com0_tec_power"
        desc = "This value represents the power from COM0 TEC"
        addr = 117
        self.parameters[name] = PataraParameter(name, address=addr, func=4, read_rate=-1.0,
                                                conversion_factor=1.0, desc=desc)

        self.input_register_read_range = [(0, 33, 3.0), (112, 117, 1.0)]
