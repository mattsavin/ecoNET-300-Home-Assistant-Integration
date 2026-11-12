"""Climate entity for ecoMAX360i heating circuits."""

import math
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    PRESET_COMFORT,
    PRESET_ECO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Econet300Api
from .common import EconetDataCoordinator
from .common_functions import is_ecomax360i_controller, round_to_step
from .const import DOMAIN, SERVICE_API, SERVICE_COORDINATOR, _numeric_or_none
from .const.processors import TEMP_NOT_CONNECTED_VALUE
from .device_grouping import component_device_info
from .entity import _main_device_info

CIRCUIT1_WORK_STATE_PARAM = "236"
CIRCUIT1_COMFORT_TEMP_PARAM = "238"  # Day temp
CIRCUIT1_ECO_TEMP_PARAM = "239"  # Night temp
CIRCUIT1_THERMOSTAT_KEY = "Circuit1thermostat"

# ecoMAX360i Circuit 1 work states:
# 0 = Off, 1 = Day mode (Comfort), 2 = Night mode (Eco), 3 = Schedule
WORK_STATE_OFF = 0
WORK_STATE_DAY = 1
WORK_STATE_NIGHT = 2
WORK_STATE_SCHEDULE = 3


def _work_state_for_hvac_mode(hvac_mode: HVACMode) -> int:
    """Translate an HVAC mode to a supported circuit work state."""
    if hvac_mode == HVACMode.OFF:
        return WORK_STATE_OFF
    if hvac_mode == HVACMode.AUTO:
        return WORK_STATE_SCHEDULE
    if hvac_mode == HVACMode.HEAT:
        return WORK_STATE_DAY
    raise HomeAssistantError(f"Unsupported HVAC mode: {hvac_mode}")


def _finite_number(value: Any) -> float | None:
    """Return a finite float, or None."""
    numeric = _numeric_or_none(value)
    return numeric if numeric is not None and math.isfinite(numeric) else None


def _info_param_number(data: dict[str, Any], key: str) -> float | None:
    """Extract a numeric value from informationParams if present."""
    info = (data.get("informationParams") or {}).get(key)
    if isinstance(info, list) and len(info) > 1:
        inner = info[1]
        if isinstance(inner, list) and len(inner) > 0 and len(inner[0]) > 0:
            return _finite_number(inner[0][0])
    return None


def _valid_circuit_param(data: dict[str, Any], param_id: str, name: str) -> bool:
    """Validate that a required circuit parameter exists and is editable."""
    entry = (data.get("editParams") or {}).get(param_id)
    if not isinstance(entry, dict):
        return False
    return (
        entry.get("name") == name
        and entry.get("edit") is True
        and not entry.get("locked", False)
    )


def _climate_platform_supported(data: dict[str, Any]) -> bool:
    """Return True when this controller supports the circuit climate entity."""
    sys_params = data.get("sysParams") or {}
    return (
        is_ecomax360i_controller(sys_params.get("controllerID"))
        and sys_params.get("protocolType") == "gm3_pomp"
        and _valid_circuit_param(data, CIRCUIT1_WORK_STATE_PARAM, "Circuit1WorkState")
        and _valid_circuit_param(
            data, CIRCUIT1_COMFORT_TEMP_PARAM, "Circuit1ComfortTemp"
        )
    )


class EconetCircuitClimate(CoordinatorEntity[EconetDataCoordinator], ClimateEntity):
    """Climate entity combining room thermostat, targets, and operating modes."""

    _attr_has_entity_name = True
    _attr_translation_key = "circuit1"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.1
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.AUTO, HVACMode.OFF]
    _attr_preset_modes = [PRESET_COMFORT, PRESET_ECO]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: EconetDataCoordinator, api: Econet300Api) -> None:
        """Initialize the climate entity without device I/O."""
        super().__init__(coordinator)
        self._api = api
        self._attr_unique_id = f"{api.uid}-circuit1"
        self._attr_device_info = _main_device_info(api)

    @property
    def device_info(self) -> Any:
        """Group circuit controls separately from the physical room sensor."""
        return (
            component_device_info(self.coordinator, self._api, "Circuit1WorkState")
            or self._attr_device_info
        )

    @property
    def _comfort_entry(self) -> dict[str, Any]:
        return (
            (self.coordinator.data or {})
            .get("editParams", {})
            .get(CIRCUIT1_COMFORT_TEMP_PARAM, {})
        )

    @property
    def _eco_entry(self) -> dict[str, Any]:
        return (
            (self.coordinator.data or {})
            .get("editParams", {})
            .get(CIRCUIT1_ECO_TEMP_PARAM, {})
        )

    @property
    def _work_state_entry(self) -> dict[str, Any]:
        return (
            (self.coordinator.data or {})
            .get("editParams", {})
            .get(CIRCUIT1_WORK_STATE_PARAM, {})
        )

    @property
    def _work_state(self) -> int | None:
        val = self._work_state_entry.get("value")
        if isinstance(val, (int, float)):
            return int(val)
        return None

    @property
    def native_current_temperature(self) -> float | None:
        """Return current room temperature from Circuit1thermostat."""
        reg_params = (self.coordinator.data or {}).get("regParams", {})
        value = _finite_number(reg_params.get(CIRCUIT1_THERMOSTAT_KEY))
        if value is None or value == TEMP_NOT_CONNECTED_VALUE:
            return None
        return value

    @property
    def native_target_temperature(self) -> float | None:
        """Return the active target temperature (Day temp or Night temp)."""
        if self._work_state == WORK_STATE_NIGHT:
            return _finite_number(self._eco_entry.get("value"))
        return _finite_number(self._comfort_entry.get("value"))

    @property
    def min_temp(self) -> float:
        """Return minimum target temperature from editParams."""
        minv = _finite_number(self._comfort_entry.get("minv"))
        return minv if minv is not None else 10.0

    @property
    def max_temp(self) -> float:
        """Return maximum target temperature from editParams."""
        maxv = _finite_number(self._comfort_entry.get("maxv"))
        return maxv if maxv is not None else 35.0

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return current HVAC mode based on Circuit1WorkState."""
        state = self._work_state
        if state == WORK_STATE_OFF:
            return HVACMode.OFF
        if state == WORK_STATE_SCHEDULE:
            return HVACMode.AUTO
        if state in (WORK_STATE_DAY, WORK_STATE_NIGHT):
            return HVACMode.HEAT
        return None

    @property
    def preset_mode(self) -> str | None:
        """Return current preset mode (comfort for Day, eco for Night)."""
        state = self._work_state
        if state == WORK_STATE_DAY:
            return PRESET_COMFORT
        if state == WORK_STATE_NIGHT:
            return PRESET_ECO
        return None

    @property
    def _is_heating_active(self) -> bool:
        """Return True when telemetry indicates heat is being supplied to Circuit 1."""
        if self.hvac_mode == HVACMode.OFF:
            return False

        data = self.coordinator.data or {}
        reg = data.get("regParams") or {}

        # Check 3-way diverter valve (0 = central heating, 3 = domestic hot water)
        flap = reg.get("flapValveStates")
        if flap == 3:
            # Valve is actively routed to DHW cylinder recharge
            return False

        # Positive thermal power delivered to the heating circuit (> 0 kW).
        thermal_power = _info_param_number(data, "212")
        if thermal_power is not None and thermal_power > 0.05:
            return True

        # Heat pump compressor running on central heating.
        comp = _finite_number(reg.get("AxenCompressorFreq"))
        if comp is not None and comp > 0:
            return True

        # Circulation pump running while circulating water delivers heat
        # (e.g. post-DHW recharge residual heat dissipation or buffer circulation)
        flow_rate = _info_param_number(data, "231")
        pump_running = (flow_rate is not None and flow_rate > 0) or (
            reg.get("AxenUpperPump") not in (None, 0, "0", "off")
        )

        if pump_running:
            flow_temp = _info_param_number(data, "14")
            ret_temp = _info_param_number(data, "15")
            room_temp = self.native_current_temperature

            if flow_temp is not None:
                # Flow is warmer than return (positive delta-T heat emission)
                if ret_temp is not None and flow_temp > ret_temp + 0.3:
                    return True
                # Or water is significantly warmer than room temperature
                if room_temp is not None and flow_temp > room_temp + 2.0:
                    return True

        return False

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return current HVAC action."""
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._is_heating_active:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return circuit target details and heating activity as attributes."""
        data = self.coordinator.data or {}
        reg = data.get("regParams") or {}

        heat_demanded = None
        info_26 = (data.get("informationParams") or {}).get("26")
        if isinstance(info_26, list) and len(info_26) > 1:
            inner = info_26[1]
            if isinstance(inner, list) and len(inner) > 0 and len(inner[0]) > 0:
                heat_demanded = str(inner[0][0]) == "0"

        flap = reg.get("flapValveStates")
        flap_str = (
            {0: "central_heating", 3: "domestic_hot_water"}.get(flap)
            if flap is not None
            else None
        )

        return {
            "day_target_temperature": _finite_number(self._comfort_entry.get("value")),
            "night_target_temperature": _finite_number(self._eco_entry.get("value")),
            "circuit_work_state": self._work_state,
            "heat_demanded": heat_demanded,
            "is_heating": self._is_heating_active,
            "compressor_frequency_hz": _finite_number(reg.get("AxenCompressorFreq")),
            "diverter_valve": flap_str,
            "flow_temperature": _info_param_number(data, "14"),
            "return_temperature": _info_param_number(data, "15"),
            "thermal_power_kw": _info_param_number(data, "212"),
            "flow_rate_lmin": _info_param_number(data, "231"),
        }

    @property
    def available(self) -> bool:
        """Return True when coordinator and parameters are available."""
        data = self.coordinator.data or {}
        health = data.get("_health") or {}
        return bool(
            super().available
            and not health.get("stale", False)
            and health.get("online", True)
            and _climate_platform_supported(data)
        )

    async def async_turn_on(self) -> None:
        """Resume the controller's heating schedule."""
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        """Stop circuit heating."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode by writing Circuit1WorkState."""
        if not self.available:
            raise HomeAssistantError("Climate entity is unavailable")

        target_state = _work_state_for_hvac_mode(hvac_mode)

        if not await self._api.set_param(CIRCUIT1_WORK_STATE_PARAM, target_state):
            raise HomeAssistantError("Controller rejected the circuit work state write")

        self.coordinator.force_edit_params_refresh()
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode by switching to Day mode (comfort) or Night mode (eco)."""
        if not self.available:
            raise HomeAssistantError("Climate entity is unavailable")

        if preset_mode == PRESET_COMFORT:
            target_state = WORK_STATE_DAY
        elif preset_mode == PRESET_ECO:
            target_state = WORK_STATE_NIGHT
        else:
            raise HomeAssistantError(f"Unsupported preset mode: {preset_mode}")

        if not await self._api.set_param(CIRCUIT1_WORK_STATE_PARAM, target_state):
            raise HomeAssistantError("Controller rejected the preset mode write")

        self.coordinator.force_edit_params_refresh()
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature and optionally change the operating mode."""
        if not self.available:
            raise HomeAssistantError("Climate entity is unavailable")

        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        target_state = self._work_state
        if hvac_mode is not None:
            target_state = _work_state_for_hvac_mode(hvac_mode)

        raw_temp = kwargs.get(ATTR_TEMPERATURE)
        temp = _finite_number(raw_temp)
        if temp is None or not (self.min_temp <= temp <= self.max_temp):
            raise HomeAssistantError(
                f"Target temperature {raw_temp} outside [{self.min_temp}, {self.max_temp}]"
            )

        step = self.target_temperature_step or 0.1
        send_val = round_to_step(temp, step)

        # Schedule and Off edit the Day target; only explicit Night uses Eco.
        target_param = (
            CIRCUIT1_ECO_TEMP_PARAM
            if target_state == WORK_STATE_NIGHT
            else CIRCUIT1_COMFORT_TEMP_PARAM
        )

        if not await self._api.set_param(target_param, send_val):
            raise HomeAssistantError(
                f"Controller rejected temperature write to param {target_param}"
            )

        try:
            if hvac_mode is not None:
                if not await self._api.set_param(
                    CIRCUIT1_WORK_STATE_PARAM, target_state
                ):
                    raise HomeAssistantError(
                        "Controller rejected the circuit work state write"
                    )
        finally:
            # The target changed even if the subsequent mode write failed.
            self.coordinator.force_edit_params_refresh()
            await self.coordinator.async_request_refresh()


# Older HA releases consume the legacy names; do not override deprecated
# members on HA 2026.11+, where native temperature properties are supported.
if not hasattr(ClimateEntity, "native_current_temperature"):
    setattr(
        EconetCircuitClimate,
        "current_temperature",
        EconetCircuitClimate.native_current_temperature,
    )
    setattr(
        EconetCircuitClimate,
        "target_temperature",
        EconetCircuitClimate.native_target_temperature,
    )
    setattr(
        EconetCircuitClimate,
        "temperature_unit",
        property(lambda self: self._attr_native_temperature_unit),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate platform for supported controllers."""
    services = hass.data[DOMAIN][entry.entry_id]
    coordinator: EconetDataCoordinator = services[SERVICE_COORDINATOR]
    data = coordinator.data or {}

    if _climate_platform_supported(data):
        api: Econet300Api = services[SERVICE_API]
        async_add_entities([EconetCircuitClimate(coordinator, api)])
