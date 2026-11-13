"""Circuit selection is applied by real platform setup without network access."""

from unittest.mock import MagicMock

import pytest

from custom_components.econet300.climate import async_setup_entry
from tests.test_climate import make_coordinator


@pytest.mark.asyncio
async def test_unselected_new_climate_is_not_created():
    """An explicit empty selection suppresses a new circuit 1 climate."""
    coordinator = make_coordinator()
    hass = MagicMock()
    hass.data = {
        "econet300": {
            "entry": {
                "coordinator": coordinator,
                "api": MagicMock(uid="test-controller"),
            }
        }
    }
    entry = MagicMock(entry_id="entry", options={"selected_circuits": []})
    added = MagicMock()
    await async_setup_entry(hass, entry, added)
    assert not added.called or not added.call_args[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "kind"),
    [("number", "number"), ("select", "select"), ("switch", "switch")],
)
async def test_edit_parameter_sources_filtered(platform, kind):
    """Actual edit parameter factories use protocol names, not display IDs."""
    import importlib

    coordinator = make_coordinator()
    coordinator.data["editParamCatalog"] = {
        "11": {"name": "Circuit1WorkState", "kind": kind},
        "12": {"name": "Circuit2WorkState", "kind": kind},
        "13": {"name": "UnknownThing", "kind": kind},
    }
    hass = MagicMock()
    hass.data = {
        "econet300": {
            "entry": {"coordinator": coordinator, "api": MagicMock(uid="test")}
        }
    }
    entry = MagicMock(entry_id="entry", options={"selected_circuits": ["2"]})
    added = MagicMock()
    await importlib.import_module(
        f"custom_components.econet300.{platform}"
    ).async_setup_entry(hass, entry, added)
    ids = {e.unique_id for e in added.call_args[0][0]}
    assert "test-edit_11" not in ids
    assert {"test-edit_12", "test-edit_13"} <= ids


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["sensor", "binary_sensor"])
async def test_sensor_sources_filtered_not_custom_display_names(platform):
    """Both custom entities and real register keys use their original source."""
    import importlib
    from unittest.mock import AsyncMock

    coordinator = make_coordinator()
    coordinator.data["regParams"].update(
        {"TempCircuit2": 20, "Circuit1Test": 1, "unrelated": 3}
    )
    hass = MagicMock()
    hass.data = {
        "econet300": {
            "entry": {"coordinator": coordinator, "api": MagicMock(uid="test")}
        }
    }
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    entry = MagicMock(
        entry_id="entry",
        options={
            "selected_circuits": ["2"],
            "custom_entities": {
                "one": {
                    "entity_type": platform,
                    "key": "Circuit1Test",
                    "source": "regParams",
                    "name": "Harmless",
                },
                "two": {
                    "entity_type": platform,
                    "key": "TempCircuit2",
                    "source": "regParams",
                    "name": "Circuit1 misleading",
                },
            },
        },
    )
    added = MagicMock()
    await importlib.import_module(
        f"custom_components.econet300.{platform}"
    ).async_setup_entry(hass, entry, added)
    ids = {e.unique_id for e in added.call_args[0][0]}
    assert "test-custom_regParams_Circuit1Test" not in ids
    assert "test-custom_regParams_TempCircuit2" in ids
    if platform == "sensor":
        assert "test-Circuit1Test" not in ids
        assert "test-TempCircuit2" in ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "controller", "expected"),
    [
        ({}, "ecoMAX360i", True),
        ({"selected_circuits": []}, "ecoMAX360i", False),
        ({"selected_circuits": ["1"]}, "ecoMAX360i", True),
        ({"selected_circuits": []}, "ecoMAX810P-L", True),
    ],
)
async def test_sensor_selection_defaults_and_supported_scope(
    options, controller, expected
):
    """Selection never changes unsupported controllers or missing options."""
    from unittest.mock import AsyncMock
    from custom_components.econet300.sensor import async_setup_entry

    coordinator = make_coordinator(controller_id=controller)
    coordinator.data["regParams"]["Circuit1Probe"] = 20
    hass = MagicMock()
    hass.data = {
        "econet300": {
            "entry": {"coordinator": coordinator, "api": MagicMock(uid="test")}
        }
    }
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    added = MagicMock()
    await async_setup_entry(hass, MagicMock(entry_id="entry", options=options), added)
    assert (
        "test-Circuit1Probe" in {e.unique_id for e in added.call_args[0][0]}
    ) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["sensor", "binary_sensor"])
async def test_custom_numeric_key_does_not_use_edit_catalog(platform):
    """An unrelated current-data ID must not collide with an edit parameter ID."""
    import importlib
    from unittest.mock import AsyncMock

    coordinator = make_coordinator()
    coordinator.data["regParamsData"] = {"42": 1}
    coordinator.data["editParamCatalog"] = {"42": {"name": "Circuit2WorkState"}}
    coordinator.data["rmData"] = {"currentDataParams": {"42": {"name": "Runtime"}}}
    hass = MagicMock()
    hass.data = {
        "econet300": {
            "entry": {"coordinator": coordinator, "api": MagicMock(uid="test")}
        }
    }
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    entry = MagicMock(
        entry_id="entry",
        options={
            "selected_circuits": [],
            "custom_entities": {
                "x": {"entity_type": platform, "source": "regParamsData", "key": "42"}
            },
        },
    )
    added = MagicMock()
    await importlib.import_module(
        f"custom_components.econet300.{platform}"
    ).async_setup_entry(hass, entry, added)
    assert "test-custom_regParamsData_42" in {
        e.unique_id for e in added.call_args[0][0]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["sensor", "binary_sensor"])
@pytest.mark.parametrize("source", ["regParamsData", "rmCurrentDataParams"])
async def test_custom_current_data_metadata_filters_circuit(platform, source):
    """A current-data entry with a circuit protocol name is filtered."""
    import importlib
    import json
    from pathlib import Path
    from unittest.mock import AsyncMock

    fixture = Path(__file__).parent / "fixtures/ecoMAX920P1-O/rmData.json"
    rm_data = json.loads(fixture.read_text())
    rm_data["currentDataParams"]["42"] = {
        "special": 0,
        "unit": 4,
        "name": "Circuit2WorkState",
    }
    coordinator = make_coordinator()
    coordinator.data["rmData"] = rm_data
    coordinator.data["regParamsData"] = {"42": 1}
    hass = MagicMock()
    hass.data = {
        "econet300": {
            "entry": {"coordinator": coordinator, "api": MagicMock(uid="test")}
        }
    }
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    entry = MagicMock(
        entry_id="entry",
        options={
            "selected_circuits": ["1"],
            "custom_entities": {
                "x": {"entity_type": platform, "source": source, "key": "42"}
            },
        },
    )
    added = MagicMock()
    await importlib.import_module(
        f"custom_components.econet300.{platform}"
    ).async_setup_entry(hass, entry, added)
    assert f"test-custom_{source}_42" not in {
        e.unique_id for e in added.call_args[0][0]
    }
