"""Constants for the Phyn Local integration."""

from datetime import timedelta

DOMAIN = "phyn_local"

# JNAP action URN base and specific actions used by this integration.
JNAP_URN_BASE = "http://phyn.com/jnap/"

JNAP_ACTION_GET_DEVICE_INFO = f"{JNAP_URN_BASE}core/GetDeviceInfo"
JNAP_ACTION_ATTRIBUTE_GET = f"{JNAP_URN_BASE}attribute/get"
JNAP_ACTION_GET_SHUTOFF_VALVE_STATE = f"{JNAP_URN_BASE}shutoff/GetShutoffValveState"
JNAP_ACTION_SET_SHUTOFF_VALVE_STATE = f"{JNAP_URN_BASE}shutoff/SetShutoffValveState"

# The device ships with a fixed, non-configurable local admin credential.
JNAP_USERNAME = "admin"
JNAP_PASSWORD = "admin"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
