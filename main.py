# This is where the magic happens!
# This file is executed on every boot (including wake-boot from deepsleep)
# Created By: Michael Pham

"""
Built for the PySquared FC Board
Version: 2.0.0
Published: Nov 19, 2024
"""

import gc
import time

import digitalio
import microcontroller

try:
    # from board_definitions import proveskit_rp2040_v4 as board
    raise ImportError
except ImportError:
    import board

import os

import lib.pysquared.functions as functions
import lib.pysquared.nvm.register as register
from lib.pysquared.cdh import CommandDataHandler
from lib.pysquared.config.config import Config
from lib.pysquared.hardware.busio import _spi_init, initialize_i2c_bus
from lib.pysquared.hardware.digitalio import initialize_pin
from lib.pysquared.hardware.imu.manager.lsm6dsox import LSM6DSOXManager
from lib.pysquared.hardware.magnetometer.manager.lis2mdl import LIS2MDLManager
from lib.pysquared.hardware.radio.manager.sx126x import SX126xManager
from lib.pysquared.logger import Logger
from lib.pysquared.nvm.counter import Counter
from lib.pysquared.nvm.flag import Flag
from lib.pysquared.rtc.manager.microcontroller import MicrocontrollerManager
from lib.pysquared.satellite import Satellite
from lib.pysquared.sleep_helper import SleepHelper
from lib.pysquared.watchdog import Watchdog
from version import __version__

rtc = MicrocontrollerManager()

logger: Logger = Logger(
    error_counter=Counter(index=register.ERRORCNT, datastore=microcontroller.nvm),
    colorized=False,
)

logger.info(
    "Booting",
    hardware_version=os.uname().version,
    software_version=__version__,
)

loiter_time: int = 5

try:
    for i in range(loiter_time):
        logger.info(f"Code Starting in {loiter_time-i} seconds")
        time.sleep(1)

    watchdog = Watchdog(logger, board.WDT_WDI)
    watchdog.pet()

    logger.debug("Initializing Config")
    config: Config = Config("config.json")

    # TODO(nateinaction): fix spi init
    spi0 = _spi_init(
        logger,
        board.SPI1_SCK,
        board.SPI1_MOSI,
        board.SPI1_MISO,
    )

    radio = SX126xManager(
        logger,
        config.radio,
        Flag(index=register.FLAG, bit_index=7, datastore=microcontroller.nvm),
        spi0,
        initialize_pin(logger, board.SPI0_CS0, digitalio.Direction.OUTPUT, True),
        board.RF2_IO0,
        initialize_pin(logger, board.RF1_RST, digitalio.Direction.OUTPUT, True),
        board.RF2_IO4,
    )

    i2c1 = initialize_i2c_bus(
        logger,
        board.I2C1_SCL,
        board.I2C1_SDA,
        100000,
    )

    magnetometer = LIS2MDLManager(logger, i2c1)

    imu = LSM6DSOXManager(logger, i2c1, 0x6B)

    c = Satellite(logger, config)

    sleep_helper = SleepHelper(c, logger, watchdog)

    cdh = CommandDataHandler(config, logger, radio)

    f = functions.functions(
        c,
        logger,
        config,
        sleep_helper,
        radio,
        magnetometer,
        imu,
        watchdog,
        cdh,
    )

    def initial_boot():
        watchdog.pet()
        f.beacon()
        watchdog.pet()
        f.listen()
        watchdog.pet()

    try:
        c.boot_count.increment()

        logger.info(
            "FC Board Stats",
            bytes_remaining=gc.mem_free(),
            boot_number=c.boot_count.get(),
        )

        initial_boot()

    except Exception as e:
        logger.error("Error in Boot Sequence", e)

    finally:
        pass

    def send_imu_data():
        logger.info("Looking to get imu data...")
        IMUData = []
        watchdog.pet()
        logger.info("IMU has baton")
        IMUData = imu.get_gyro_data()
        watchdog.pet()
        radio.send(IMUData)

    def main():
        f.beacon()

        f.listen_loiter()

        f.state_of_health()

        f.listen_loiter()

        f.all_face_data()
        watchdog.pet()
        f.send_face()

        f.listen_loiter()

        send_imu_data()

        f.listen_loiter()

        f.joke()

        f.listen_loiter()

    def critical_power_operations():
        initial_boot()
        watchdog.pet()

        sleep_helper.long_hibernate()

    def minimum_power_operations():
        initial_boot()
        watchdog.pet()

        sleep_helper.short_hibernate()

    ######################### MAIN LOOP ##############################
    try:
        while True:
            # L0 automatic tasks no matter the battery level
            c.check_reboot()

            if c.power_mode == "critical":
                critical_power_operations()

            elif c.power_mode == "minimum":
                minimum_power_operations()

            elif c.power_mode == "normal":
                main()

            elif c.power_mode == "maximum":
                main()

            else:
                f.listen()

    except Exception as e:
        logger.critical("Critical in Main Loop", e)
        time.sleep(10)
        microcontroller.on_next_reset(microcontroller.RunMode.NORMAL)
        microcontroller.reset()
    finally:
        logger.info("Going Neutral!")

except Exception as e:
    logger.critical("An exception occured within main.py", e)
