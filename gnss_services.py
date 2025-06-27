from modules.A7670E import A7670E, gnss_data
import logging

class GnssServices:
    """
    Provides an abstraction layer for GNSS functionalities, handling data
    retrieval and formatting for the API.
    """
    def __init__(self, hardware_manager):
        """
        Initializes the service and gets the GNSS module from the hardware manager.
        """
        self.gnss_module = hardware_manager.get_gnss_module()
        if self.gnss_module is None:
            logging.warning("GNSS module not loaded or available. GNSS services will be disabled.")
        else:
            logging.info("GNSS services initialized successfully.")

    def get_gnss_data(self) -> gnss_data | None:
        """Retrieves raw gnss_data object from the underlying module."""
        if self.gnss_module:
            return self.gnss_module.get_gnss_data()
        return None

    def get_gnss_data_json(self):
        """
        Returns a JSON-serializable dictionary of GNSS data with clear error states.
        """
        if not self.gnss_module:
            # This error indicates the hardware failed to initialize or power on.
            return {"error": "GNSS hardware module is not available or failed to initialize."}

        data = self.get_gnss_data()
        
        if data:
            # A fix of 2 (2D) or 3 (3D) is considered a valid location lock.
            if data.fix in [2, 3]:
                return {
                    "status": "success",
                    "fix_type": f"{data.fix}D",
                    "latitude": data.lat,
                    "longitude": data.lon,
                    "altitude_m": data.altitude,
                    "speed_kmh": data.speed_kmh,
                    "course_deg": data.course,
                    "satellites_in_view": data.satellites
                }
            else:
                # The hardware is on, but it can't get a location lock. This is common.
                return {
                    "status": "pending_fix",
                    "error": "GNSS module is active but has no satellite fix.",
                    "fix_type": "No Fix",
                    "satellites_in_view": data.satellites
                }
        else:
            # This error means there was a problem communicating with the module right now.
            return {"error": "Could not retrieve data from GNSS module. Communication may have failed."}
