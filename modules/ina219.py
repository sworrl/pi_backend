# modules/ina219.py
# Basic driver for the INA219 sensor found on Waveshare UPS HATs.
import smbus
import time

class INA219:
    _REG_CONFIG = 0x00
    _REG_SHUNTVOLTAGE = 0x01
    _REG_BUSVOLTAGE = 0x02
    _REG_POWER = 0x03
    _REG_CURRENT = 0x04
    _REG_CALIBRATION = 0x05

    def __init__(self, i2c_bus=1, addr=0x42):
        self.bus = smbus.SMBus(i2c_bus)
        self.addr = addr
        # Set configuration to default
        self.bus.write_i2c_block_data(self.addr, self._REG_CONFIG, [0x01, 0x9F])
        # Calibrate
        self.bus.write_i2c_block_data(self.addr, self._REG_CALIBRATION, [0x00, 0x00])

    def _read_voltage(self, register):
        read = self.bus.read_word_data(self.addr, register)
        swapped = ((read & 0xFF) << 8) | (read >> 8)
        return (swapped >> 3) * 4

    def get_bus_voltage_V(self):
        return self._read_voltage(self._REG_BUSVOLTAGE) * 0.001

    def get_shunt_voltage_mV(self):
        return self._read_voltage(self._REG_SHUNTVOLTAGE)

    def get_current_mA(self):
        # Sometimes a sharp load will reset the sensor, so we'll be defensive here.
        try:
            self.bus.write_word_data(self.addr, self._REG_CALIBRATION, 0)
            read = self.bus.read_word_data(self.addr, self._REG_CURRENT)
            swapped = ((read & 0xFF) << 8) | (read >> 8)
            return swapped
        except Exception:
            return 0 # Return 0 if there's an I2C error