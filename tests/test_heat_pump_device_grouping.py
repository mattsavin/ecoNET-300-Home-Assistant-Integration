"""Capability-gated ecoMAX360i component ownership."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.econet300.common import build_edit_param_catalog


@pytest.fixture
def heat_pump_data(load_fixture):
    """Return the coordinator shape, including the unmodified schematic payload."""
    registers = load_fixture("ecoMAX360-cf8", "regParams.json")
    editable = load_fixture("ecoMAX360-cf8", "editParams.json")
    return {
        "sysParams": load_fixture("ecoMAX360-cf8", "sysParams.json"),
        "regParams": registers.get("curr", registers),
        "regParamsData": registers,
        "editParams": editable["data"],
        "editParamsFull": editable,
        "editParamCatalog": build_edit_param_catalog(editable),
    }


def test_thermostat_measurement_and_circuit_controls_have_distinct_owners(
    heat_pump_data,
):
    """A physical room sensor is not the circuit's climate control."""
    from custom_components.econet300.device_grouping import component_for_key

    assert component_for_key(heat_pump_data, "Circuit1thermostat") == "thermostat_1"
    assert component_for_key(heat_pump_data, "Circuit1ComfortTemp") == "circuit_1"
    assert component_for_key(heat_pump_data, "Circuit1WorkState") == "circuit_1"


@pytest.mark.parametrize(
    ("key", "owner"),
    [
        ("AxenCompressorFreq", "heat_pump"),
        ("ActualFlowTemp", "heat_pump"),
        ("ThermalPower", "heat_pump"),
        ("PeriodicEnergyConsumption", "heat_pump"),
        ("TempCWU", "dhw"),
        ("HDWTSetPoint", "dhw"),
        ("HDWStartOneLoading", "dhw"),
        ("cwuTZ", "dhw"),
        ("circuit1TZ", "circuit_1"),
        ("TempClutch", "circuit_1"),
        ("TempCircuit2", "controller"),
        ("Circuit2ComfortTemp", "controller"),
        ("Circuit2thermostatTemp", "controller"),
        ("TempBuforDown", "controller"),
        ("TempWthr", "controller"),
        ("heating_work_state", "controller"),
        ("controllerID", "controller"),
        ("softVer", "gateway"),
        ("signal", "gateway"),
        ("", "gateway"),
    ],
)
def test_explicit_ownership_uses_confirmed_components(heat_pump_data, key, owner):
    """Do not promote unused default circuits or a hidden buffer to devices."""
    from custom_components.econet300.device_grouping import component_for_key

    assert component_for_key(heat_pump_data, key) == owner


def test_fixture_components_exclude_phantom_circuits_and_hidden_buffer(heat_pump_data):
    """The fixture reports usable hardware even with Circuit 1 switched Off."""
    from custom_components.econet300.device_grouping import supported_components

    assert supported_components(heat_pump_data) == {
        "gateway",
        "controller",
        "heat_pump",
        "circuit_1",
        "thermostat_1",
        "dhw",
    }


@pytest.mark.parametrize(
    "sentinel", [999, 65535, None, True, float("nan"), float("inf")]
)
def test_invalid_thermostat_reading_does_not_discover_a_device(
    heat_pump_data, sentinel
):
    """Sensor-disconnected values are not hardware presence evidence."""
    from custom_components.econet300.device_grouping import supported_components

    heat_pump_data["regParams"]["Circuit1thermostat"] = sentinel
    assert "thermostat_1" not in supported_components(heat_pump_data)
    assert "circuit_1" in supported_components(heat_pump_data)


def test_visible_buffer_is_grouped_without_changing_existing_entities(heat_pump_data):
    """Use the schematic visibility flag, not an incidental finite pipe reading."""
    from custom_components.econet300.device_grouping import component_for_key

    heat_pump_data["regParamsData"]["schemaParams"]["Bufor"][1] = True
    assert component_for_key(heat_pump_data, "TempBuforDown") == "buffer"
    assert component_for_key(heat_pump_data, "BuforSETTINGS") == "buffer"


def test_older_fixture_buffer_requires_configuration_and_valid_temperature(
    load_fixture,
):
    """Without schematic data, both buffer configuration and a reading are required."""
    from custom_components.econet300.device_grouping import supported_components

    registers = load_fixture("ecoMAX360i", "regParams.json")
    editable = load_fixture("ecoMAX360i", "editParams.json")
    data = {
        "sysParams": load_fixture("ecoMAX360i", "sysParams.json"),
        "regParams": registers,
        "editParams": editable["data"],
    }
    assert "buffer" in supported_components(data)
    data["regParams"]["TempBuforDown"] = 999
    assert "buffer" not in supported_components(data)


@pytest.mark.parametrize(
    ("controller", "protocol"), [("ecoMAX810P", "em"), ("ecoMAX360i", "em")]
)
def test_other_controller_paths_remain_unchanged(heat_pump_data, controller, protocol):
    """Grant grouping must not affect unrelated controller/protocol combinations."""
    from custom_components.econet300.device_grouping import component_for_key

    heat_pump_data["sysParams"].update(controllerID=controller, protocolType=protocol)
    assert component_for_key(heat_pump_data, "TempCWU") is None


@pytest.fixture
def component_coordinator(heat_pump_data):
    """Represent the topology registered at setup, without changing live HA."""
    from custom_components.econet300.device_grouping import supported_components

    return SimpleNamespace(
        data=heat_pump_data,
        component_device_tree=True,
        component_device_ids={
            key: f"{key}-registry-id" for key in supported_components(heat_pump_data)
        },
        single_device_tree=False,
        controller_device_id="gateway-registry-id",
    )


def test_component_device_info_has_stable_ids_and_no_invented_hardware(
    component_coordinator,
):
    """Logical groups do not claim the controller's hardware or firmware."""
    from custom_components.econet300.device_grouping import component_device_info

    api = MagicMock(
        uid="test-uid",
        host="http://test",
        sw_rev="gateway-firmware",
        hw_ver="gateway-hw",
    )
    for key, suffix in (
        ("Circuit1thermostat", "thermostat-1"),
        ("Circuit1ComfortTemp", "circuit-1"),
        ("TempCWU", "huw"),
        ("AxenCompressorFreq", "heat-pump"),
    ):
        info = component_device_info(component_coordinator, api, key)
        assert info["identifiers"] == {("econet300", f"test-uid-{suffix}")}
        assert (
            not {"sw_version", "hw_version", "serial_number", "model_id"} & info.keys()
        )
    assert component_device_info(component_coordinator, api, "softVer") is None


def test_grouping_is_explicitly_opt_in(component_coordinator):
    """Legacy Split and Single mode keep their existing device_info path."""
    from custom_components.econet300.device_grouping import component_device_info

    component_coordinator.component_device_tree = False
    assert component_device_info(component_coordinator, MagicMock(), "TempCWU") is None


@pytest.mark.parametrize(
    ("kind", "suffix", "unique_id"),
    [
        ("sensor", "thermostat-1", "test-uid-Circuit1thermostat"),
        ("number", "circuit-1", "test-uid-edit_238"),
        ("select", "circuit-1", "test-uid-edit_236"),
        ("switch", "huw", "test-uid-edit_115"),
        ("climate", "circuit-1", "test-uid-circuit1"),
        ("water_heater", "huw", "test-uid-dhw"),
        ("boost", "huw", "test-uid-dhw-boost"),
        ("calendar", "huw", "test-uid-schedule_water_heater"),
    ],
)
def test_platform_entities_share_component_ownership_without_new_unique_ids(
    component_coordinator, kind, suffix, unique_id
):
    """All platform entry points use the same ownership rules."""
    from custom_components.econet300.calendar import EconetScheduleCalendar
    from custom_components.econet300.climate import EconetCircuitClimate
    from custom_components.econet300.number import EditParamNumber
    from custom_components.econet300.select import EditParamSelect
    from custom_components.econet300.sensor import (
        EconetSensor,
        create_sensor_entity_description,
    )
    from custom_components.econet300.switch import EditParamSwitch
    from custom_components.econet300.water_heater import (
        EconetWaterHeater,
        EconetDhwBoostButton,
    )

    coordinator = MagicMock()
    coordinator.data = component_coordinator.data
    coordinator.component_device_tree = True
    coordinator.component_device_ids = component_coordinator.component_device_ids
    coordinator.single_device_tree = False
    api = MagicMock(
        uid="test-uid",
        host="http://test",
        sw_rev="1.0",
        hw_ver="1",
        model_id="ecoMAX360i",
    )
    factories = {
        "sensor": lambda: EconetSensor(
            create_sensor_entity_description("Circuit1thermostat"), coordinator, api
        ),
        "number": lambda: EditParamNumber(coordinator, api, "238"),
        "select": lambda: EditParamSelect(coordinator, api, "236"),
        "switch": lambda: EditParamSwitch(coordinator, api, "115"),
        "climate": lambda: EconetCircuitClimate(coordinator, api),
        "water_heater": lambda: EconetWaterHeater(coordinator, api),
        "boost": lambda: EconetDhwBoostButton(coordinator, api),
        "calendar": lambda: EconetScheduleCalendar(
            coordinator, api, "water_heater", "cwuTZ", "huw"
        ),
    }
    entity = factories[kind]()
    assert entity.unique_id == unique_id
    assert entity.device_info["identifiers"] == {("econet300", f"test-uid-{suffix}")}


@pytest.mark.parametrize("style", ["typed_dict", "dataclass"])
def test_modern_circuit_child_payload_is_not_a_physical_device(
    component_coordinator, monkeypatch, style
):
    """Support both HA child-info representations without changing vessel identities."""
    from dataclasses import dataclass
    from custom_components.econet300 import device_grouping

    @dataclass(kw_only=True)
    class ChildInfo:
        identifiers: set
        name: str
        parent_device_id: str
        translation_key: str
        translation_placeholders: dict

    constructor = ChildInfo if style == "dataclass" else lambda **fields: fields
    monkeypatch.setattr(device_grouping, "_CHILD_DEVICE_INFO", constructor)
    api = MagicMock(uid="test-uid")
    info = device_grouping.component_device_info(
        component_coordinator, api, "Circuit1ComfortTemp"
    )
    payload = vars(info) if style == "dataclass" else info
    assert payload["parent_device_id"] == "controller-registry-id"
    assert payload["identifiers"] == {("econet300", "test-uid-circuit-1")}
    assert set(payload) == {
        "identifiers",
        "name",
        "parent_device_id",
        "translation_key",
        "translation_placeholders",
    }
    vessel = device_grouping.component_device_info(
        component_coordinator, api, "TempCWU"
    )
    assert vessel["identifiers"] == {("econet300", "test-uid-huw")}
    assert "parent_device_id" not in vessel
    assert "model" not in vessel


@pytest.mark.parametrize("modern_link", [True, False])
def test_physical_components_link_to_the_controller_compatibly(
    component_coordinator, monkeypatch, modern_link
):
    """Only the gateway/controller relationship uses the old root identifier."""
    from custom_components.econet300 import device_grouping

    monkeypatch.setattr(device_grouping, "_SUPPORTS_VIA_DEVICE_ID", modern_link)
    api = MagicMock(uid="test-uid")
    info = device_grouping.component_device_info(
        component_coordinator, api, "Circuit1thermostat"
    )
    if modern_link:
        assert info["via_device_id"] == "controller-registry-id"
        assert "via_device" not in info
    else:
        assert info["via_device"] == ("econet300", "test-uid-controller")
        assert "via_device_id" not in info


def test_new_layout_does_not_change_the_existing_default():
    """The new migration is never applied merely by upgrading the integration."""
    from custom_components.econet300.common import EconetDataCoordinator
    from custom_components.econet300.const import (
        DEFAULT_DEVICE_GROUPING,
        DEVICE_GROUPING_COMPONENTS,
        DEVICE_GROUPING_SPLIT,
    )

    coordinator = object.__new__(EconetDataCoordinator)
    coordinator._device_grouping = DEFAULT_DEVICE_GROUPING
    assert DEFAULT_DEVICE_GROUPING == DEVICE_GROUPING_SPLIT
    assert coordinator.component_device_tree is False
    coordinator._device_grouping = DEVICE_GROUPING_COMPONENTS
    assert coordinator.component_device_tree is True
    assert coordinator.single_device_tree is False


def test_zero_default_is_not_thermostat_evidence_for_a_missing_circuit(heat_pump_data):
    """String-form zero defaults must not create a circuit when its probe is absent."""
    from custom_components.econet300.device_grouping import supported_components

    heat_pump_data["regParams"]["TempClutch"] = 999
    heat_pump_data["regParams"]["Circuit1thermostat"] = "0.0"
    assert "circuit_1" not in supported_components(heat_pump_data)
