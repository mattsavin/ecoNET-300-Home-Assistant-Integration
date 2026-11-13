"""Options flow tests for hiding existing raw edit-parameter entities."""

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock

from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
import pytest
import pytest_asyncio

from custom_components.econet300.config_flow import EconetOptionsFlowHandler
from custom_components.econet300.const import DOMAIN, SERVICE_API, SERVICE_COORDINATOR


def _make_entry(options: dict | None = None) -> ConfigEntry:
    return ConfigEntry(
        data={},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        entry_id="entry1",
        minor_version=1,
        options=options or {"other": "kept"},
        source=SOURCE_USER,
        subentries_data=None,
        title="ecoNET300",
        unique_id="uid-entry1",
        version=1,
    )


@pytest_asyncio.fixture
async def setup_flow(hass, monkeypatch):
    """Prepare a real entity registry and mocked runtime coordinator for options flow."""
    monkeypatch.setattr(Store, "async_load", AsyncMock(return_value=None))
    monkeypatch.setattr(Store, "async_delay_save", MagicMock())
    registry = er.async_get(hass)
    await registry.async_load()
    entry = _make_entry()
    entries = {entry.entry_id: entry}
    hass.config_entries.async_get_entry.side_effect = entries.get
    hass.config_entries.async_get_known_entry.side_effect = entries.get
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_update_entry = MagicMock()

    catalog = {
        "103": {"name": "HDWTSetPoint", "kind": "number"},
        "500": {"name": "PumpPower", "kind": "number"},
        "501": {"name": "ValveSpeed", "kind": "select"},
    }
    coordinator = MagicMock()
    coordinator.data = {"editParamCatalog": catalog}
    api = MagicMock()
    api.uid = "controller"
    hass.data[DOMAIN] = {
        entry.entry_id: {
            SERVICE_API: api,
            SERVICE_COORDINATOR: coordinator,
        }
    }

    protected = registry.async_get_or_create(
        "number",
        DOMAIN,
        "controller-edit_103",
        suggested_object_id="dhw_target",
        original_name="DHW target temperature (103)",
        config_entry=entry,
    )
    first = registry.async_get_or_create(
        "number",
        DOMAIN,
        "controller-edit_500",
        suggested_object_id="pump_power",
        original_name="Pump power (500)",
        config_entry=entry,
    )
    second = registry.async_get_or_create(
        "select",
        DOMAIN,
        "controller-edit_501",
        suggested_object_id="valve_speed",
        original_name="Valve speed (501)",
        config_entry=entry,
    )
    user_hidden = registry.async_get_or_create(
        "number",
        DOMAIN,
        "controller-edit_502",
        suggested_object_id="hidden_param",
        original_name="Hidden param (502)",
        config_entry=entry,
        hidden_by=er.RegistryEntryHider.USER,
    )
    catalog["502"] = {"name": "HiddenParam", "kind": "number"}

    handler = EconetOptionsFlowHandler()
    handler.hass = hass
    handler.handler = entry.entry_id

    return {
        "hass": hass,
        "registry": registry,
        "entry": entry,
        "handler": handler,
        "coordinator": coordinator,
        "api": api,
        "protected": protected,
        "first": first,
        "second": second,
        "user_hidden": user_hidden,
    }


@pytest.mark.asyncio
async def test_menu_and_preview_default_empty_without_mutations(setup_flow):
    """Init menu exposes the tool, preview defaults to nothing selected, and cancel writes nothing."""
    handler = setup_flow["handler"]
    registry = setup_flow["registry"]

    menu = await handler.async_step_init()
    assert menu["type"] == FlowResultType.MENU
    assert "hide_existing_raw" in menu["menu_options"]

    step1 = await handler.async_step_hide_existing_raw()
    assert step1["type"] == FlowResultType.FORM
    assert step1["step_id"] == "hide_existing_raw"
    schema = step1["data_schema"]
    assert schema({})["selected_entities"] == []
    # Protected and user-hidden entries are not selectable
    selectable = schema.schema["selected_entities"].options
    assert setup_flow["first"].entity_id in selectable
    assert setup_flow["second"].entity_id in selectable
    assert setup_flow["protected"].entity_id not in selectable
    assert setup_flow["user_hidden"].entity_id not in selectable

    # Empty selection aborts cleanly with zero registry or options writes
    empty_res = await handler.async_step_hide_existing_raw({"selected_entities": []})
    assert empty_res["type"] == FlowResultType.ABORT
    assert empty_res["reason"] == "no_raw_entities_selected"
    assert registry.async_get(setup_flow["first"].entity_id).hidden_by is None
    setup_flow["hass"].config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_preview_confirm_cancel_and_apply_selected_only(setup_flow):
    """Explicit confirmation hides only selected entries and preserves everything else."""
    handler = setup_flow["handler"]
    registry = setup_flow["registry"]
    first = setup_flow["first"]
    second = setup_flow["second"]
    registry.async_update_entity(first.entity_id, name="My custom name")

    await handler.async_step_hide_existing_raw()
    confirm = await handler.async_step_hide_existing_raw(
        {"selected_entities": [first.entity_id]}
    )
    assert confirm["type"] == FlowResultType.FORM
    assert confirm["step_id"] == "confirm_hide_raw"
    assert confirm["description_placeholders"]["count"] == "1"
    assert first.entity_id in confirm["description_placeholders"]["entities"]
    assert registry.async_get(first.entity_id).hidden_by is None

    # Submitting with confirm=False aborts without mutations
    declined = await handler.async_step_confirm_hide_raw({"confirm": False})
    assert declined["type"] == FlowResultType.ABORT
    assert declined["reason"] == "hide_cancelled"
    assert registry.async_get(first.entity_id).hidden_by is None

    # Now select and confirm
    await handler.async_step_hide_existing_raw()
    await handler.async_step_hide_existing_raw({"selected_entities": [first.entity_id]})
    result = await handler.async_step_confirm_hide_raw({"confirm": True})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "hide_raw_result"
    assert result["description_placeholders"]["applied_count"] == "1"
    assert result["description_placeholders"]["skipped_count"] == "0"

    updated_first = registry.async_get(first.entity_id)
    assert updated_first.hidden_by == er.RegistryEntryHider.INTEGRATION
    assert updated_first.disabled_by is None
    assert updated_first.name == "My custom name"
    assert registry.async_get(second.entity_id).hidden_by is None
    assert (
        registry.async_get(setup_flow["user_hidden"].entity_id).hidden_by
        == er.RegistryEntryHider.USER
    )

    done = await handler.async_step_hide_raw_result({})
    assert done["type"] == FlowResultType.ABORT
    assert done["reason"] == "hide_complete"
    setup_flow["hass"].config_entries.async_update_entry.assert_not_called()
    setup_flow["hass"].config_entries.async_reload.assert_not_called()
    setup_flow["api"].set_param.assert_not_called()


@pytest.mark.asyncio
async def test_stale_change_between_preview_and_confirm_performs_zero_writes(
    setup_flow,
):
    """If any selected entry changes before confirmation, make zero writes and re-select."""
    handler = setup_flow["handler"]
    registry = setup_flow["registry"]
    first = setup_flow["first"]
    second = setup_flow["second"]

    await handler.async_step_hide_existing_raw()
    await handler.async_step_hide_existing_raw(
        {"selected_entities": [first.entity_id, second.entity_id]}
    )
    # User hides second in HA UI before confirming
    registry.async_update_entity(second.entity_id, hidden_by=er.RegistryEntryHider.USER)

    res = await handler.async_step_confirm_hide_raw({"confirm": True})
    assert res["type"] == FlowResultType.FORM
    assert res["step_id"] == "hide_existing_raw"
    assert res["errors"]["base"] == "selection_stale"
    assert registry.async_get(first.entity_id).hidden_by is None
    assert registry.async_get(second.entity_id).hidden_by == er.RegistryEntryHider.USER


@pytest.mark.asyncio
async def test_no_eligible_entries_aborts_cleanly(setup_flow):
    """If no visible eligible raw entities exist, abort immediately."""
    handler = setup_flow["handler"]
    registry = setup_flow["registry"]
    registry.async_update_entity(
        setup_flow["first"].entity_id, hidden_by=er.RegistryEntryHider.USER
    )
    registry.async_update_entity(
        setup_flow["second"].entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION
    )
    res = await handler.async_step_hide_existing_raw()
    assert res["type"] == FlowResultType.ABORT
    assert res["reason"] == "no_eligible_raw_entities"


@pytest.mark.asyncio
async def test_options_flow_manager_preserves_options_on_hide_abort(hass, setup_flow):
    """Drive OptionsFlowManager end-to-end and verify options stay untouched."""
    from homeassistant import config_entries

    entry = setup_flow["entry"]
    registry = setup_flow["registry"]
    first = setup_flow["first"]
    entries = {entry.entry_id: entry}
    manager = config_entries.OptionsFlowManager(hass)
    manager._progress = {}
    hass.config_entries.async_get_known_entry.side_effect = entries.get
    hass.config_entries.options = manager
    from custom_components.econet300.config_flow import ConfigFlow

    hass.config_entries.async_entries.return_value = [entry]
    flow = ConfigFlow.async_get_options_flow(entry)
    flow.hass = hass
    flow.handler = entry.entry_id
    menu = await flow.async_step_init()
    assert "hide_existing_raw" in menu["menu_options"]
    select_form = await flow.async_step_hide_existing_raw()
    confirm_form = await flow.async_step_hide_existing_raw(
        select_form["data_schema"]({"selected_entities": [first.entity_id]})
    )
    assert confirm_form["step_id"] == "confirm_hide_raw"
    result_form = await flow.async_step_confirm_hide_raw({"confirm": True})
    assert result_form["step_id"] == "hide_raw_result"
    abort_res = await flow.async_step_hide_raw_result({})
    finish_res = await manager.async_finish_flow(flow, abort_res)
    assert finish_res["type"] == FlowResultType.ABORT
    assert (
        registry.async_get(first.entity_id).hidden_by
        == er.RegistryEntryHider.INTEGRATION
    )
    setup_flow["hass"].config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_partial_write_failure_reports_accurate_counts(setup_flow, monkeypatch):
    """When one registry update fails, the summary shows actual applied and skipped counts."""
    handler = setup_flow["handler"]
    registry = setup_flow["registry"]
    first = setup_flow["first"]
    second = setup_flow["second"]
    real_update = registry.async_update_entity

    def fail_second(entity_id, **kwargs):
        if entity_id == second.entity_id:
            raise RuntimeError("write error")
        return real_update(entity_id, **kwargs)

    monkeypatch.setattr(registry, "async_update_entity", fail_second)
    await handler.async_step_hide_existing_raw()
    await handler.async_step_hide_existing_raw(
        {"selected_entities": [first.entity_id, second.entity_id]}
    )
    result = await handler.async_step_confirm_hide_raw({"confirm": True})
    assert result["step_id"] == "hide_raw_result"
    assert result["description_placeholders"]["applied_count"] == "1"
    assert result["description_placeholders"]["skipped_count"] == "1"
    assert second.entity_id in result["description_placeholders"]["skipped"]
    assert (
        registry.async_get(first.entity_id).hidden_by
        == er.RegistryEntryHider.INTEGRATION
    )
    assert registry.async_get(second.entity_id).hidden_by is None
