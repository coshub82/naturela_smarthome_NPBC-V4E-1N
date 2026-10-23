"""Select entities for Naturela burner fuel control."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_ID,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    fuel_to_display_value,
    get_fuel_from_state,
    get_mode_from_state,
    pack_state,
)

_LOGGER = logging.getLogger(__name__)

FUEL_OPTIONS = ["1", "2", "3", "4"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Naturela fuel selector."""
    data = hass.data[DOMAIN][entry.entry_id]
    device_id = entry.data.get(CONF_DEVICE_ID, 6548)
    async_add_entities([NaturelaFuelSelect(data["coordinator"], data["api"], device_id)])


class NaturelaFuelSelect(CoordinatorEntity, SelectEntity):
    """Choose the pellet fuel level (1-4) while preserving current ON/OFF/TIMER mode."""

    _attr_has_entity_name = True
    _attr_name = "Fuel"

    def __init__(self, coordinator, api, device_id: int) -> None:
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_fuel"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(device_id))},
            "name": "Pellet Stove",
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @property
    def options(self) -> list[str]:
        """Return the available fuel settings."""
        return FUEL_OPTIONS

    @property
    def current_option(self) -> str | None:
        """Return the current fuel selection (1 to 4) from the packed state value."""
        if not self.coordinator.data:
            return None

        raw_state = self.coordinator.data.get("State")
        if raw_state is None:
            return None

        try:
            fuel_value = get_fuel_from_state(int(raw_state))
        except (TypeError, ValueError):
            return None

        if fuel_value < 0 or fuel_value > 3:
            return None

        return str(fuel_to_display_value(fuel_value))

    async def async_select_option(self, option: str) -> None:
        """Set the selected fuel while keeping the current mode intact."""
        if option not in FUEL_OPTIONS:
            _LOGGER.warning("Invalid fuel option %r for Naturela burner", option)
            return

        current_data = self.coordinator.data or {}
        raw_state = current_data.get("State", 0)
        try:
            current_state = int(raw_state)
        except (TypeError, ValueError):
            current_state = 0

        current_mode = get_mode_from_state(current_state)
        fuel_value = int(option) - 1
        new_state = pack_state(current_mode, fuel_value)

        success = await self._api.set_state(new_state)
        if not success:
            _LOGGER.error("Failed to set fuel to %s on Naturela burner", option)
            return

        self.coordinator.async_set_updated_data({**current_data, "State": new_state})
