"""Conservative circuit source classification for a future opt-in filter."""

import pytest

from custom_components.econet300 import device_grouping


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("Circuit1WorkState", 1),
        ("Circuit2thermostatTemp", 2),
        ("TempCircuit7", 7),
        ("circuit1TZ", 1),
        ("TempClutch", 1),
        ("HeatDemanded", 1),
        ("Circuit10WorkState", None),
        ("Circuit8WorkState", None),
        ("Mixer1Temp", None),
        ("HDWTSetPoint", None),
        ("236", None),
    ],
)
def test_classifies_original_protocol_keys_without_inferring_presence(key, expected):
    """Classify known source names independently of readings or device grouping."""
    classifier = getattr(device_grouping, "circuit_number_for_key", None)
    assert callable(classifier), "A shared circuit classifier is needed"
    data = {"sysParams": {"controllerID": "ecoMAX360i", "protocolType": "gm3_pomp"}}
    assert classifier(data, key) == expected


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"sysParams": {}},
        {"sysParams": {"controllerID": "ecoMAX360i"}},
        {"sysParams": {"controllerID": "ecoMAX360i", "protocolType": "other"}},
        {"sysParams": {"controllerID": "ecoMAX810P-L", "protocolType": "gm3_pomp"}},
    ],
)
def test_unknown_or_unsupported_controller_is_not_classified(data):
    """Missing or unverified controller evidence must not imply ownership."""
    assert device_grouping.circuit_number_for_key(data, "Circuit1WorkState") is None
