"""Tests for the ecoMAX360i climate entity."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.climate import (
    ClimateEntityFeature,
    HVACMode,
    PRESET_COMFORT,
    PRESET_ECO,
)
from homeassistant.const import ATTR_TEMPERATURE, Platform, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.econet300 import PLATFORMS


def make_coordinator(
    controller_id: str = "ecoMAX360i",
    protocol_type: str = "gm3_pomp",
    room_temp: float | None = 20.8,
    work_state: int = 3,
    comfort_temp: float = 22.5,
    eco_temp: float = 21.2,
    stale: bool = False,
    online: bool = True,
):
    """Build coordinator data mock for ecoMAX360i climate tests."""
    path = Path(__file__).parent / "fixtures" / "ecoMAX360-cf8" / "editParams.json"
    raw = json.loads(path.read_text())
    edit_data = raw["data"].copy()

    # Configure circuit 1 params in edit_data
    edit_data["236"] = {
        "name": "Circuit1WorkState",
        "value": work_state,
        "edit": True,
        "minv": 0,
        "maxv": 3,
        "mult": 1,
        "unit": 0,
    }
    edit_data["238"] = {
        "name": "Circuit1ComfortTemp",
        "value": comfort_temp,
        "edit": True,
        "minv": 10,
        "maxv": 35,
        "mult": 1,
        "unit": 0,
    }
    edit_data["239"] = {
        "name": "Circuit1EcoTemp",
        "value": eco_temp,
        "edit": True,
        "minv": 10,
        "maxv": 35,
        "mult": 1,
        "unit": 0,
    }

    coordinator = MagicMock()
    coordinator.data = {
        "sysParams": {
            "controllerID": controller_id,
            "protocolType": protocol_type,
        },
        "regParams": {"Circuit1thermostat": room_temp},
        "editParams": edit_data,
        "_health": {"stale": stale, "online": online},
    }
    coordinator.single_device_tree = False
    coordinator.controller_device_id = None
    coordinator.async_request_refresh = AsyncMock()
    coordinator.force_edit_params_refresh = MagicMock()
    return coordinator


def test_climate_platform_registered():
    """Home Assistant must load the climate platform."""
    assert Platform.CLIMATE in PLATFORMS


@pytest.mark.asyncio
async def test_setup_entry_creates_entity_for_ecomax360i():
    """Climate entity is added for supported ecoMAX360i controllers."""
    from custom_components.econet300.climate import async_setup_entry

    coordinator = make_coordinator()
    api = MagicMock(uid="test-controller")
    hass = MagicMock()
    hass.data = {"econet300": {"entry": {"api": api, "coordinator": coordinator}}}
    add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(entry_id="entry"), add_entities)

    assert add_entities.called
    entities = add_entities.call_args[0][0]
    assert len(entities) == 1
    climate = entities[0]

    assert climate.unique_id == "test-controller-circuit1"
    assert climate.temperature_unit == UnitOfTemperature.CELSIUS
    assert climate.current_temperature == 20.8
    assert climate.target_temperature == 22.5
    assert climate.target_temperature_step == 0.1
    assert climate.min_temp == 10.0
    assert climate.max_temp == 35.0
    assert climate.hvac_mode == HVACMode.AUTO
    assert climate.preset_mode is None
    assert climate.supported_features == (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )


@pytest.mark.asyncio
async def test_setup_entry_skips_unsupported_controller():
    """Unsupported controllers do not create climate entities."""
    from custom_components.econet300.climate import async_setup_entry

    coordinator = make_coordinator(controller_id="ecoMAX810P-L", protocol_type="em")
    api = MagicMock(uid="test-controller")
    hass = MagicMock()
    hass.data = {"econet300": {"entry": {"api": api, "coordinator": coordinator}}}
    add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(entry_id="entry"), add_entities)
    assert not add_entities.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("work_state", "expected_hvac", "expected_preset", "expected_target"),
    [
        (0, HVACMode.OFF, None, 22.5),
        (1, HVACMode.HEAT, PRESET_COMFORT, 22.5),
        (2, HVACMode.HEAT, PRESET_ECO, 21.2),
        (3, HVACMode.AUTO, None, 22.5),
    ],
)
async def test_work_state_mapping(
    work_state, expected_hvac, expected_preset, expected_target
):
    """Circuit1WorkState maps to HA HVAC and preset modes."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(
        work_state=work_state, comfort_temp=22.5, eco_temp=21.2
    )
    api = MagicMock(uid="test-controller")
    climate = EconetCircuitClimate(coordinator, api)

    assert climate.hvac_mode == expected_hvac
    assert climate.preset_mode == expected_preset
    assert climate.target_temperature == expected_target


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_temp", "expected_current"),
    [
        (20.8, 20.8),
        (22.85, 22.85),
        (999, None),
        (999.0, None),
        (None, None),
    ],
)
async def test_current_temperature_sentinel(raw_temp, expected_current):
    """Disconnected sentinel (999) returns None for current_temperature."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(room_temp=raw_temp)
    api = MagicMock(uid="test-controller")
    climate = EconetCircuitClimate(coordinator, api)

    assert climate.current_temperature == expected_current


@pytest.mark.asyncio
async def test_set_hvac_mode_writes_work_state():
    """Changing HVAC mode writes the correct Circuit1WorkState."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator()
    api = MagicMock(uid="test-controller", set_param=AsyncMock(return_value=True))
    climate = EconetCircuitClimate(coordinator, api)

    await climate.async_set_hvac_mode(HVACMode.OFF)
    api.set_param.assert_awaited_with("236", 0)

    await climate.async_set_hvac_mode(HVACMode.AUTO)
    api.set_param.assert_awaited_with("236", 3)

    await climate.async_set_hvac_mode(HVACMode.HEAT)
    api.set_param.assert_awaited_with("236", 1)


@pytest.mark.asyncio
async def test_set_preset_mode_writes_work_state():
    """Changing preset mode writes Day (1) or Night (2)."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator()
    api = MagicMock(uid="test-controller", set_param=AsyncMock(return_value=True))
    climate = EconetCircuitClimate(coordinator, api)

    await climate.async_set_preset_mode(PRESET_COMFORT)
    api.set_param.assert_awaited_with("236", 1)

    await climate.async_set_preset_mode(PRESET_ECO)
    api.set_param.assert_awaited_with("236", 2)


@pytest.mark.asyncio
async def test_set_temperature_in_comfort_writes_param_238():
    """Setting temperature while in Day/Comfort mode adjusts Circuit1ComfortTemp."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=1)
    api = MagicMock(uid="test-controller", set_param=AsyncMock(return_value=True))
    climate = EconetCircuitClimate(coordinator, api)

    await climate.async_set_temperature(**{ATTR_TEMPERATURE: 23.5})
    api.set_param.assert_awaited_once_with("238", 23.5)
    coordinator.force_edit_params_refresh.assert_called_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_temperature_in_eco_writes_param_239():
    """Setting temperature while in Night/Eco mode adjusts Circuit1EcoTemp."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=2)
    api = MagicMock(uid="test-controller", set_param=AsyncMock(return_value=True))
    climate = EconetCircuitClimate(coordinator, api)

    await climate.async_set_temperature(**{ATTR_TEMPERATURE: 20.5})
    api.set_param.assert_awaited_once_with("239", 20.5)


@pytest.mark.asyncio
async def test_set_temperature_rounds_to_tenth_step():
    """Target temperature writes are rounded to 0.1°C step."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=1)
    api = MagicMock(uid="test-controller", set_param=AsyncMock(return_value=True))
    climate = EconetCircuitClimate(coordinator, api)

    await climate.async_set_temperature(**{ATTR_TEMPERATURE: 21.56})
    api.set_param.assert_awaited_once_with("238", 21.6)


@pytest.mark.asyncio
async def test_set_temperature_out_of_bounds_raises():
    """Temperature writes outside [10, 35] raise HomeAssistantError."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator()
    api = MagicMock(uid="test-controller")
    climate = EconetCircuitClimate(coordinator, api)

    with pytest.raises(HomeAssistantError):
        await climate.async_set_temperature(**{ATTR_TEMPERATURE: 9.9})

    with pytest.raises(HomeAssistantError):
        await climate.async_set_temperature(**{ATTR_TEMPERATURE: 35.1})


@pytest.mark.asyncio
async def test_availability():
    """Availability reflects coordinator health and parameter presence."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator()
    api = MagicMock(uid="test-controller")
    climate = EconetCircuitClimate(coordinator, api)
    assert climate.available is True

    stale_coordinator = make_coordinator(stale=True)
    climate_stale = EconetCircuitClimate(stale_coordinator, api)
    assert climate_stale.available is False

    offline_coordinator = make_coordinator(online=False)
    climate_offline = EconetCircuitClimate(offline_coordinator, api)
    assert climate_offline.available is False


@pytest.mark.asyncio
async def test_hvac_action_off_when_mode_is_off():
    """hvac_action is OFF when hvac_mode is OFF."""
    from homeassistant.components.climate import HVACAction
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=0)
    api = MagicMock(uid="test-controller")
    climate = EconetCircuitClimate(coordinator, api)

    assert climate.hvac_action == HVACAction.OFF


@pytest.mark.asyncio
async def test_hvac_action_idle_when_demand_has_no_heat_delivery():
    """Demand alone is diagnostic and does not prove heat is being supplied."""
    from homeassistant.components.climate import HVACAction
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=3)
    coordinator.data["informationParams"] = {"26": [False, [["0", 0, 1]]]}
    api = MagicMock(uid="test-controller")
    climate = EconetCircuitClimate(coordinator, api)

    assert climate.hvac_action == HVACAction.IDLE
    assert climate.extra_state_attributes["heat_demanded"] is True
    assert climate.extra_state_attributes["is_heating"] is False


@pytest.mark.asyncio
async def test_hvac_action_idle_when_demand_off():
    """hvac_action is IDLE when HeatDemanded signal is 1 (off)."""
    from homeassistant.components.climate import HVACAction
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=3)
    coordinator.data["informationParams"] = {"26": [False, [["1", 0, 1]]]}
    api = MagicMock(uid="test-controller")
    climate = EconetCircuitClimate(coordinator, api)

    assert climate.hvac_action == HVACAction.IDLE
    assert climate.extra_state_attributes["heat_demanded"] is False
    assert climate.extra_state_attributes["is_heating"] is False


@pytest.mark.asyncio
async def test_hvac_action_heating_when_compressor_active():
    """hvac_action is HEATING when compressor is running and valve is on CH."""
    from homeassistant.components.climate import HVACAction
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=1)
    coordinator.data["regParams"]["flapValveStates"] = 0
    coordinator.data["regParams"]["AxenCompressorFreq"] = 45.0
    api = MagicMock(uid="test-controller")
    climate = EconetCircuitClimate(coordinator, api)

    assert climate.hvac_action == HVACAction.HEATING
    assert climate.extra_state_attributes["compressor_frequency_hz"] == 45.0
    assert climate.extra_state_attributes["diverter_valve"] == "central_heating"


@pytest.mark.asyncio
async def test_hvac_action_heating_during_post_dhw_circulation():
    """hvac_action is HEATING when compressor is off but warm water circulates post-DHW."""
    from homeassistant.components.climate import HVACAction
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=3, room_temp=20.5)
    coordinator.data["informationParams"] = {
        "26": [False, [["1", 0, 1]]],
        "14": [True, [["42.5", 1, 0]]],
        "15": [True, [["35.0", 1, 0]]],
        "231": [True, [["15.2", 30, 0]]],
    }
    coordinator.data["regParams"]["flapValveStates"] = 0
    coordinator.data["regParams"]["AxenCompressorFreq"] = 0
    api = MagicMock(uid="test-controller")
    climate = EconetCircuitClimate(coordinator, api)

    assert climate.hvac_action == HVACAction.HEATING
    assert climate.extra_state_attributes["is_heating"] is True
    assert climate.extra_state_attributes["flow_temperature"] == 42.5
    assert climate.extra_state_attributes["return_temperature"] == 35.0
    assert climate.extra_state_attributes["flow_rate_lmin"] == 15.2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial_state", "requested_mode", "expected_state"),
    [
        (0, HVACMode.HEAT, 1),
        (2, HVACMode.HEAT, 1),
        (1, HVACMode.OFF, 0),
        (2, HVACMode.AUTO, 3),
    ],
)
async def test_temperature_service_honours_requested_mode(
    hass, initial_state, requested_mode, expected_state
):
    """Combined requests set the Day target before changing the operating mode."""
    from homeassistant.components.climate import async_service_temperature_set
    from homeassistant.core import ServiceCall

    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=initial_state)
    api = MagicMock(uid="test-controller", set_param=AsyncMock(return_value=True))
    climate = EconetCircuitClimate(coordinator, api)
    climate.hass = hass
    service_call = ServiceCall(
        hass,
        "climate",
        "set_temperature",
        {"temperature": 22.5, "hvac_mode": requested_mode},
    )

    await async_service_temperature_set(climate, service_call)

    assert [call.args for call in api.set_param.await_args_list] == [
        ("238", 22.5),
        ("236", expected_state),
    ]
    coordinator.force_edit_params_refresh.assert_called_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "initial_state", "expected_state", "required_features"),
    [
        ("turn_on", 0, 3, [ClimateEntityFeature.TURN_ON]),
        ("turn_off", 1, 0, [ClimateEntityFeature.TURN_OFF]),
        ("turn_off", 2, 0, [ClimateEntityFeature.TURN_OFF]),
        ("toggle", 0, 3, [ClimateEntityFeature.TURN_ON, ClimateEntityFeature.TURN_OFF]),
        ("toggle", 3, 0, [ClimateEntityFeature.TURN_ON, ClimateEntityFeature.TURN_OFF]),
    ],
)
async def test_on_off_services_resume_schedule_or_stop_circuit(
    hass, service, initial_state, expected_state, required_features
):
    """Standard HA actions dispatch successfully with explicit schedule semantics."""
    from homeassistant.core import ServiceCall
    from homeassistant.helpers.service import entity_service_call

    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=initial_state)
    api = MagicMock(uid="test-controller", set_param=AsyncMock(return_value=True))
    climate = EconetCircuitClimate(coordinator, api)
    climate.hass = hass
    climate.entity_id = "climate.test_circuit_1"
    service_call = ServiceCall(
        hass, "climate", service, {"entity_id": climate.entity_id}
    )

    await entity_service_call(
        hass,
        {climate.entity_id: climate},
        f"async_{service}",
        service_call,
        required_features,
    )

    api.set_param.assert_awaited_once_with("236", expected_state)
    coordinator.force_edit_params_refresh.assert_called_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_hvac_action_idle_during_dhw_recharge():
    """DHW routing takes precedence over demand and heat pump activity."""
    from homeassistant.components.climate import HVACAction

    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=3)
    coordinator.data["regParams"].update(
        flapValveStates=3, AxenCompressorFreq=45, AxenUpperPump=1
    )
    coordinator.data["informationParams"] = {
        "26": [False, [["0", 0, 1]]],
        "212": [None, [["5.0", 7, 0]]],
        "14": [True, [["45.0", 1, 0]]],
        "15": [True, [["35.0", 1, 0]]],
        "231": [True, [["15.0", 30, 0]]],
    }
    climate = EconetCircuitClimate(coordinator, MagicMock(uid="test-controller"))

    assert climate.hvac_action == HVACAction.IDLE
    assert climate.extra_state_attributes["heat_demanded"] is True
    assert climate.extra_state_attributes["is_heating"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"temperature": 22.5, "hvac_mode": HVACMode.COOL},
        {"temperature": 9.9, "hvac_mode": HVACMode.HEAT},
        {"temperature": float("nan"), "hvac_mode": HVACMode.HEAT},
    ],
)
async def test_combined_request_validates_all_inputs_before_writing(kwargs):
    """Invalid temperature or mode must not partially change the controller."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=0)
    api = MagicMock(uid="test-controller", set_param=AsyncMock(return_value=True))
    climate = EconetCircuitClimate(coordinator, api)

    with pytest.raises(HomeAssistantError):
        await climate.async_set_temperature(**kwargs)

    api.set_param.assert_not_awaited()
    coordinator.force_edit_params_refresh.assert_not_called()
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("write_results", "expected_writes", "refresh_count"),
    [
        ([False], [("238", 22.5)], 0),
        ([True, False], [("238", 22.5), ("236", 1)], 1),
        (
            [True, HomeAssistantError("Connection lost")],
            [("238", 22.5), ("236", 1)],
            1,
        ),
    ],
)
async def test_combined_request_reports_failed_writes(
    write_results, expected_writes, refresh_count
):
    """Do not enable heating after target failure; refresh after partial success."""
    from custom_components.econet300.climate import EconetCircuitClimate

    coordinator = make_coordinator(work_state=0)
    api = MagicMock(
        uid="test-controller", set_param=AsyncMock(side_effect=write_results)
    )
    climate = EconetCircuitClimate(coordinator, api)

    with pytest.raises(HomeAssistantError):
        await climate.async_set_temperature(temperature=22.5, hvac_mode=HVACMode.HEAT)

    assert [call.args for call in api.set_param.await_args_list] == expected_writes
    assert coordinator.force_edit_params_refresh.call_count == refresh_count
    assert coordinator.async_request_refresh.await_count == refresh_count
