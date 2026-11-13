"""Readable names for observed raw parameters retain their entity identity."""

import json
from pathlib import Path

import pytest

from custom_components.econet300.common_functions import friendly_edit_param_name
from custom_components.econet300.number import (
    EditParamNumber,
    _create_edit_param_numbers,
)
from custom_components.econet300.select import _create_edit_param_selects
from custom_components.econet300.switch import _create_edit_param_switches
from tests.test_edit_params import _coordinator, _make_api


# Keys and IDs are observed in the ecoMAX360i editParams fixture. Descriptions
# expand the protocol spelling without inferring conditions or physical metadata.
CASES = [
    ("236", "Circuit1WorkState", "Circuit 1 operating state"),
    ("261", "Circuit1BaseTemp", "Circuit 1 base temperature"),
    ("262", "Circuit1TempReduction", "Circuit 1 temperature reduction"),
    ("286", "Circuit2WorkState", "Circuit 2 operating state"),
    ("291", "Circuit2MinSetTempRad", "Circuit 2 minimum radiator set temperature"),
    ("292", "Circuit2MaxSetTempRad", "Circuit 2 maximum radiator set temperature"),
    ("311", "Circuit2BaseTemp", "Circuit 2 base temperature"),
    ("312", "Circuit2TempReduction", "Circuit 2 temperature reduction"),
    ("336", "Circuit3WorkState", "Circuit 3 operating state"),
    ("341", "Circuit3MinSetTemp", "Circuit 3 minimum set temperature"),
    ("342", "Circuit3MaxSetTemp", "Circuit 3 maximum set temperature"),
    ("361", "Circuit3BaseTemp", "Circuit 3 base temperature"),
    ("362", "Circuit3TempReduction", "Circuit 3 temperature reduction"),
]


@pytest.mark.parametrize(("pid", "key", "label"), CASES)
def test_observed_protocol_names_are_readable(pid, key, label):
    """Expand only parameter keys observed in the captured fixture."""
    fixture = Path(__file__).parent / "fixtures/ecoMAX360i/editParams.json"
    raw = json.loads(fixture.read_text())
    assert raw["data"][pid]["name"] == key
    assert friendly_edit_param_name(key) == label


@pytest.mark.parametrize(
    ("factory", "kind"),
    [
        (_create_edit_param_numbers, "number"),
        (_create_edit_param_selects, "select"),
        (_create_edit_param_switches, "switch"),
    ],
)
def test_entity_name_changes_without_changing_unique_id(factory, kind):
    """Each editable entity type preserves its existing parameter-based ID."""
    catalog = {"286": {"name": "Circuit2WorkState", "value": 1, "kind": kind}}
    entity = factory(_coordinator(catalog), _make_api())[0]
    assert entity.name == "Circuit 2 operating state (286)"
    assert entity.unique_id == "test-uid-edit_286"


def test_number_value_suffix_identity_is_unchanged():
    """The secondary numeric entity keeps its distinct value suffix."""
    catalog = {
        "286": {
            "name": "Circuit2WorkState",
            "value": 1,
            "kind": "select",
            "expose_number": True,
        }
    }
    entity = EditParamNumber(_coordinator(catalog), _make_api(), "286")
    assert entity.name == "Circuit 2 operating state (286) value"
    assert entity.unique_id == "test-uid-edit_286_value"


@pytest.mark.parametrize(
    ("raw_key", "expected"),
    [
        ("EreaseEnergy", "Erase energy"),
        ("ImmersionBoosttimeLeft", "Immersion boost time left"),
        ("ImmersionBoostsettings", "Immersion boost settings"),
        ("Circuit1boosttimeleft", "Circuit 1 boost time left"),
        ("Mixer2valvedeadzone", "Mixer 2 valve deadzone"),
        ("Axenregister2100RW", "Outdoor unit mode (register 2100)"),
        ("Axenregister2101RW", "Outdoor unit run request"),
        ("Axenregister2103RW", "Outdoor unit command bitfield"),
        ("Axenregister2150RWRebootUnit", "Reboot heat pump outdoor unit"),
        ("Axen2155uhsPumpManualPreset", "Heat pump water pump manual preset"),
        ("HoldingRegister6050", "Heat pump standby pump speed"),
        ("HoldingRegister6061", "Heat pump minimum pump speed"),
        ("HoldingRegister6271", "Heat pump maximum pump speed"),
        ("PwmInverse", "PWM inverse"),
        ("ahsPumpkp", "AHS pump Kp"),
        ("ahsPumpti", "AHS pump Ti"),
        ("ahsPumptd", "AHS pump Td"),
        ("ahsPumpts", "AHS pump Ts"),
        ("ahsPumpMinSpeed", "AHS pump min speed"),
        ("ahsPumpMaxSpeed", "AHS pump max speed"),
        ("ahsPumpMaxStep", "AHS pump max step"),
        ("AhsTempDiffHystStart", "AHS temperature differential hysteresis start"),
        ("AhsTempDiffHystStop", "AHS temperature differential hysteresis stop"),
        ("Hfanspeed06244", "Heat pump fan speed step 0"),
        ("Hfanspeed16231", "Heat pump fan speed step 1"),
        ("Hfanspeed26232", "Heat pump fan speed step 2"),
        ("Hfanspeed36233", "Heat pump fan speed step 3"),
        ("Mix2pidkp", "Mix 2 PID Kp"),
        ("Mix7pidti", "Mix 7 PID Ti"),
        ("CopCalculateModuleSettings", "COP calculate module settings"),
        ("UhsPumpPresetInAhsSupport", "UHS pump preset in AHS support"),
        ("CircuitCritHeatTempIgnoreTime", "Circuit critical heat temp ignore time"),
        ("workState2", "System operating mode bitfield"),
        ("AxenWorkState", "Heat pump work state"),
        ("CirculationTempStart", "Circulation start temperature"),
        ("HeatersPermTemp", "Heaters permitted temperature"),
        ("HeatersForceTemp", "Heaters forced temperature"),
        ("HeatSourceTempInc", "Heat source temp increase"),
        ("MTHStime1", "MTHS time 1"),
        ("MTHStimeDhw2", "MTHS time DHW 2"),
        ("Circuit4WorkState", "Circuit 4 operating state"),
        ("Circuit4BaseTemp", "Circuit 4 base temperature"),
        ("Circuit4TempReduction", "Circuit 4 temperature reduction"),
        ("Circuit4DownHist", "Circuit 4 hysteresis"),
        ("Circuit4MinSetTempRad", "Circuit 4 minimum radiator set temperature"),
        ("Circuit4MaxSetTempRad", "Circuit 4 maximum radiator set temperature"),
        ("Circuit7WorkState", "Circuit 7 operating state"),
        ("heatersPermTemp", "Heaters permitted temperature"),
        ("heatersForceTemp", "Heaters forced temperature"),
        ("AXEN2155uhsPumpManualPreset", "Heat pump water pump manual preset"),
        ("AXEN_2155-uhsPumpManualPreset", "Heat pump water pump manual preset"),
        ("Axenregister2150RWreboot_unit", "Reboot heat pump outdoor unit"),
        ("AXEN_REGISTER_2100_RW", "Outdoor unit mode (register 2100)"),
        ("axenRegister2101RW", "Outdoor unit run request"),
        ("HoldingRegister_6050", "Heat pump standby pump speed"),
        ("H_FAN_SPEED_0_6244", "Heat pump fan speed step 0"),
    ],
)
def test_observed_typos_and_squashed_tokens_are_cleaned(raw_key, expected):
    """Expand observed squashed words and vendor typos without changing unique IDs."""
    assert friendly_edit_param_name(raw_key) == expected
