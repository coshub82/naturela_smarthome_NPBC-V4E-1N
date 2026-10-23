"""Sensor entities for Naturela BurnerTouch pellet stove."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfMass, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BURNING_STATUS_CODES,
    CONF_DEVICE_ID,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    STATUS_NAMES,
    STATUS_OPTIONS,
    fuel_to_display_value,
)

_LOGGER = logging.getLogger(__name__)

# Track Status values we've already warned about so we don't spam the log
# every poll cycle (default 30s) with the same unknown code.
_LOGGED_UNKNOWN_STATUS: set = set()


@dataclass
class NaturelaSensorEntityDescription(SensorEntityDescription):
    """Extended description to carry the API field key."""

    api_key: str = ""
    value_multiplier: float = 1.0
    null_as_zero: bool = False  # Treat None/null API value as 0 (e.g. power when stove is off)


SENSORS: tuple[NaturelaSensorEntityDescription, ...] = (
    NaturelaSensorEntityDescription(
        key="temp_boiler",
        api_key="TempBoiler",
        name="Boiler temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
    ),
    NaturelaSensorEntityDescription(
        key="temp_dhw",
        api_key="TempDHW",
        name="DHW temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-thermometer",
    ),
    NaturelaSensorEntityDescription(
        key="temp_fume",
        api_key="TempFume",
        name="Flue gas temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:smoke",
    ),
    NaturelaSensorEntityDescription(
        key="set_temp",
        api_key="SetTemp",
        name="Target temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:target",
    ),
    NaturelaSensorEntityDescription(
        key="power_kw",
        api_key="FPower",
        name="Burner step",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        null_as_zero=True,
    ),
    NaturelaSensorEntityDescription(
        key="fire_level",
        api_key="FireLevel",
        name="Flame level",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire-circle",
        null_as_zero=True,
    ),
    NaturelaSensorEntityDescription(
        key="fuel_consumed",
        api_key="FuelConsum",
        name="Total pellet consumption",
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=None,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:silo",
    ),
    NaturelaSensorEntityDescription(
        key="output_power",
        api_key="OutputPower",
        name="Thermal output",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_multiplier=0.1,
        null_as_zero=True,
    ),
    NaturelaSensorEntityDescription(
        key="main_fan",
        api_key="MainFan",
        name="Primary fan",
        native_unit_of_measurement="%",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fan",
        null_as_zero=True,
    ),
    NaturelaSensorEntityDescription(
        key="exhaust_fan",
        api_key="ExhaustFan",
        name="Exhaust fan",
        native_unit_of_measurement="%",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fan-chevron-down",
        null_as_zero=True,
    ),
    NaturelaSensorEntityDescription(
        key="power1_threshold",
        api_key="Power1",
        name="Power level 1",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer-slow",
    ),
    NaturelaSensorEntityDescription(
        key="power2_threshold",
        api_key="Power2",
        name="Power level 2",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer-medium",
    ),
    NaturelaSensorEntityDescription(
        key="power3_threshold",
        api_key="Power3",
        name="Power level 3",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
    ),
    NaturelaSensorEntityDescription(
        key="storing",
        api_key="ErrorFlag",
        name="Alarm",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=None,
        icon="mdi:alert-circle",
        null_as_zero=True,
    ),
)

# Sensors whose values must always be finite numbers. Used to guard against
# the Naturela API returning "NaN", null, or out-of-range values on fields that
# the stove doesn't actually measure (e.g. no DHW boiler connected).
_NUMERIC_KEYS = {
    "temp_boiler",
    "temp_dhw",
    "temp_fume",
    "set_temp",
    "output_power",
    "power_kw",
    "fire_level",
    "fuel_consumed",
    "main_fan",
    "exhaust_fan",
    "power1_threshold",
    "power2_threshold",
    "power3_threshold",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Naturela sensor entities."""
    coordinator = entry.runtime_data.coordinator
    device_id = entry.data.get(CONF_DEVICE_ID, 6548)

    entities: list[SensorEntity] = [
        NaturelaStatusSensor(coordinator, device_id),
    ]
    entities += [
        NaturelaSensor(coordinator, device_id, desc)
        for desc in SENSORS
    ]

    fuel_profiles = (coordinator.data or {}).get("Fuels") if coordinator.data else []
    if fuel_profiles:
        entities.extend(
            NaturelaFuelSettingsSensor(coordinator, device_id, idx)
            for idx in range(len(fuel_profiles))
        )

    async_add_entities(entities)


class _NaturelaEntityBase(CoordinatorEntity):
    """Shared base for Naturela sensors."""

    def __init__(self, coordinator, device_id: int) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(device_id))},
            "name": "Pellet Stove",
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }


class NaturelaStatusSensor(_NaturelaEntityBase, SensorEntity):
    """Human-readable status of the stove.

    Returns one of the labels in STATUS_OPTIONS (ENUM device class) so HA's
    history graph and logbook render nicely with colored bars per state.

    Mapping logic:
    - When status code is in BURNING_STATUS_CODES (2 or 8), derive power label
      from FPower vs Power1/Power2/Power3 thresholds reported by the API
      → returns "Power1" / "Power2" / "Power3" / "PS".
    - Otherwise look up STATUS_NAMES (numeric or string key).
    - Unknown codes return "Unknown" rather than raising or polluting history
      with arbitrary values.
    """

    _attr_icon = "mdi:fire-alert"
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUS_OPTIONS

    def __init__(self, coordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_status"
        self._attr_name = "Status"

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        d = self.coordinator.data
        value = d.get("Status")
        if value is None:
            return None

        # Burning state → derive power-level label from FPower vs thresholds.
        # Matches what the Naturela controller and web portal display.
        if value in BURNING_STATUS_CODES:
            fpower = d.get("FPower") or 0
            p3 = d.get("Power3")
            p2 = d.get("Power2")
            p1 = d.get("Power1")
            if p3 is not None and fpower >= p3:
                return "Power3"
            if p2 is not None and fpower >= p2:
                return "Power2"
            if p1 is not None and fpower >= p1:
                return "Power1"
            # FPower below P1 threshold but burning → PS (Keeping)
            if fpower > 0:
                return "PS"
            # FPower=0 yet status burning → transitional, fall through to STATUS_NAMES

        label = STATUS_NAMES.get(value)
        if label is None:
            # Unknown status — log once per unique value so we can extend
            # STATUS_NAMES later. Critical for catching error states like
            # "No pellets" or "Overheating" with their actual API spelling.
            key = (type(value).__name__, value)
            if key not in _LOGGED_UNKNOWN_STATUS:
                _LOGGED_UNKNOWN_STATUS.add(key)
                _LOGGER.warning(
                    "Naturela: unknown Status value %r (type=%s) — falling back to 'Unknown'. "
                    "Please report so it can be added to STATUS_NAMES.",
                    value,
                    type(value).__name__,
                )
            return "Unknown"

        # Final safety: only return labels that are in the ENUM options list.
        if label not in STATUS_OPTIONS:
            key = ("label", label)
            if key not in _LOGGED_UNKNOWN_STATUS:
                _LOGGED_UNKNOWN_STATUS.add(key)
                _LOGGER.warning(
                    "Naturela: status label %r maps from %r but is not in STATUS_OPTIONS",
                    label,
                    value,
                )
            return "Unknown"

        return label


def _coerce_numeric(value):
    """Convert an API value to a finite float, or return None.

    Guards against:
    - None
    - float('nan') / float('inf')
    - string "NaN", "null", "", etc.
    - any value that can't be converted to a finite float
    """
    if value is None:
        return None
    # Catch actual float NaN/Inf first (isinstance check before str conversion)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, (int, bool)):
        return float(value)
    # String or other — try to convert, treat "NaN"/"Infinity"/"" as missing
    try:
        s = str(value).strip()
        if not s or s.lower() in ("nan", "null", "none", "inf", "-inf", "infinity", "-infinity"):
            return None
        num = float(s)
        if not math.isfinite(num):
            return None
        return num
    except (TypeError, ValueError):
        return None


class NaturelaSensor(_NaturelaEntityBase, SensorEntity):
    """Generic numeric sensor based on a NaturelaSensorEntityDescription."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        device_id: int,
        description: NaturelaSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{description.key}"

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        value = self.coordinator.data.get(self.entity_description.api_key)
        if value is None:
            # For sensors where "no data" means 0 (power, fan speed, etc.),
            # return 0 instead of None so the sensor shows 0 instead of "-".
            if self.entity_description.null_as_zero:
                value = 0
            else:
                return None

        multiplier = self.entity_description.value_multiplier

        # All sensors defined here are numeric — coerce to a finite float or None.
        # Home Assistant validates finite values for TEMPERATURE / POWER device
        # classes and will raise errors on NaN / Inf, which shows up as "NaN"
        # on the dashboard.
        if self.entity_description.key in _NUMERIC_KEYS:
            num = _coerce_numeric(value)
            if num is None:
                return None
            if multiplier != 1.0:
                return round(num * multiplier, 2)
            # Preserve integer type for fields that are always whole numbers
            if isinstance(value, int) and not isinstance(value, bool):
                return int(num)
            return num

        # Fallback for any future non-numeric sensors
        if multiplier != 1.0:
            try:
                return round(float(value) * multiplier, 2)
            except (TypeError, ValueError):
                return value
        return value


class NaturelaFuelSettingsSensor(_NaturelaEntityBase, SensorEntity):
    """Expose one complete pellet fuel profile as a HA sensor with all settings as attributes."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator, device_id: int, fuel_index: int) -> None:
        super().__init__(coordinator, device_id)
        self._fuel_index = fuel_index
        self._attr_unique_id = f"{DOMAIN}_{device_id}_fuel_{fuel_index}_settings"
        self._attr_name = f"Fuel {fuel_index + 1} settings"

    def _fuel_profile(self) -> dict | None:
        if not self.coordinator.data:
            return None
        fuels = self.coordinator.data.get("Fuels") or []
        if not fuels or self._fuel_index >= len(fuels):
            return None
        return fuels[self._fuel_index]

    @property
    def native_value(self):
        fuel = self._fuel_profile()
        if fuel is None:
            return None
        fuel_type = int(fuel.get("FuelType", self._fuel_index))
        return f"Fuel {fuel_to_display_value(fuel_type)}"

    @property
    def extra_state_attributes(self) -> dict:
        fuel = self._fuel_profile()
        if fuel is None:
            return {}

        fuel_type = int(fuel.get("FuelType", self._fuel_index))
        attrs: dict[str, object] = {
            "fuel_type": fuel_to_display_value(fuel_type),
            "fuel_type_raw": fuel_type,
            "ci_start_fm": fuel.get("CiStartFM"),
            "ci_stop_fm": fuel.get("CiStopFM"),
            "ci_alarm_fm": fuel.get("CiAlarmFM"),
            "auto_clean_time": fuel.get("AutoCleanTime"),
            "ci_start_fc": fuel.get("CiStartFC"),
            "ci_stop_fc": fuel.get("CiStopFC"),
            "ci_alarm_fc": fuel.get("CiAlarmFC"),
            "auto_clean": fuel.get("AutoClean"),
            "intermediate_clean": fuel.get("IntermediateClean"),
            "use_fan_on_int_clean": fuel.get("UseFanOnIntClean"),
            "change_fan_speed": fuel.get("ChangeFanSpeed"),
            "burn_retr": fuel.get("BurnRetr"),
            "burn_fd_feed": fuel.get("Burn_FDFeed"),
            "burn_exh_fan": fuel.get("Burn_ExhFan"),
            "ign_heat": fuel.get("IgnHeat"),
            "ign_ph1_long": fuel.get("IgnPh1Long"),
            "ign_ph2_long": fuel.get("IgnPh2Long"),
            "ign_ph1_fan": fuel.get("IgnPh1Fan"),
            "ign_ph2_fan": fuel.get("IgnPh2Fan"),
            "stf_bfd_long": fuel.get("StfBFDLong"),
            "stf_bfd_fan": fuel.get("StfBFDFan"),
            "stf_bfd_exh_fan": fuel.get("StfBFDExhFan"),
            "stf_p1_long": fuel.get("STFP1Long"),
            "stf_p2_long": fuel.get("STFP2Long"),
            "feed_cap": fuel.get("Feed_cap"),
            "fuel_cal_v": fuel.get("FuelCalV"),
            "ext_fan": fuel.get("Ext_Fan"),
            "ext_efan": fuel.get("Ext_Efan"),
            "ci_efan": fuel.get("CI_Efan"),
            "ci_start_fan": fuel.get("CI_Start_Fan"),
            "ci_stop_fan": fuel.get("CI_Stop_Fan"),
            "ci_alarm_fan": fuel.get("CI_Alarm_Fan"),
            "is_active_ash_cleaner": fuel.get("IsActiveAshCleaner"),
            "ashc_cycle": fuel.get("AshC_Cycle"),
            "ashc_long": fuel.get("AshC_Long"),
            "power_level_1": fuel.get("PowerLevel1"),
            "power_level_2": fuel.get("PowerLevel2"),
            "power_level_3": fuel.get("PowerLevel3"),
            "power_level_s": fuel.get("PowerLevelS"),
            "power_level_interm": fuel.get("PowerLevelInterm"),
        }
        return attrs
