"""Visibility defaults for newly registered editable parameters."""

from types import SimpleNamespace

import pytest

from custom_components.econet300.common import EconetDataCoordinator
from custom_components.econet300.number import _create_edit_param_numbers
from custom_components.econet300.select import _create_edit_param_selects
from custom_components.econet300.switch import _create_edit_param_switches


@pytest.mark.parametrize("mode", ["split", "single", "components"])
@pytest.mark.parametrize("hide", [None, False, True])
def test_raw_visibility_default(hass, mode, hide):
    """Both entities for a dual-exposed parameter follow the option."""
    options = {"device_grouping": mode}
    if hide is not None:
        options["hide_new_raw_parameters"] = hide
    api = SimpleNamespace(
        uid="test", model_id="test", host="test", sw_rev="1", hw_ver="1"
    )
    coordinator = EconetDataCoordinator(hass, api, None, options)
    coordinator.data = {
        "editParamCatalog": {
            "1": {"kind": "number", "name": "number"},
            "2": {"kind": "select", "name": "select", "expose_number": True},
            "3": {"kind": "switch", "name": "switch", "expose_number": True},
        }
    }
    entities = (
        _create_edit_param_numbers(coordinator, api)
        + _create_edit_param_selects(coordinator, api)
        + _create_edit_param_switches(coordinator, api)
    )
    assert len(entities) == 5
    for entity in entities:
        assert entity.entity_registry_visible_default is (hide is not True)
        assert entity.entity_registry_enabled_default is True


@pytest.mark.asyncio
async def test_registry_preserves_existing_visibility(hass, monkeypatch):
    """HA's real registry retains user visibility when defaults change."""
    from unittest.mock import AsyncMock, MagicMock

    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers.storage import Store

    monkeypatch.setattr(Store, "async_load", AsyncMock(return_value=None))
    monkeypatch.setattr(Store, "async_delay_save", MagicMock())
    registry = er.async_get(hass)
    await registry.async_load()
    api = SimpleNamespace(
        uid="test", model_id="test", host="test", sw_rev="1", hw_ver="1"
    )
    coordinator = EconetDataCoordinator(hass, api, None, {})
    coordinator.data = {"editParamCatalog": {"1": {"kind": "number", "name": "number"}}}
    entity = _create_edit_param_numbers(coordinator, api)[0]
    old = registry.async_get_or_create("number", "econet300", entity.unique_id)
    visible = registry.async_get_or_create("number", "econet300", "existing-visible")
    registry.async_update_entity(old.entity_id, hidden_by=er.RegistryEntryHider.USER)
    coordinator.hide_new_raw_parameters = True
    entity = _create_edit_param_numbers(coordinator, api)[0]
    hidden_by = (
        None
        if entity.entity_registry_visible_default
        else er.RegistryEntryHider.INTEGRATION
    )
    again = registry.async_get_or_create(
        "number", "econet300", entity.unique_id, hidden_by=hidden_by
    )
    assert again.hidden_by == er.RegistryEntryHider.USER
    assert again.disabled_by is None
    visible_again = registry.async_get_or_create(
        "number", "econet300", visible.unique_id, hidden_by=hidden_by
    )
    assert visible_again.hidden_by is None
    fresh = registry.async_get_or_create(
        "number", "econet300", "new-id", hidden_by=hidden_by
    )
    assert fresh.hidden_by == er.RegistryEntryHider.INTEGRATION
    assert fresh.disabled_by is None
    again = registry.async_get_or_create(
        "number", "econet300", "new-id", hidden_by=None
    )
    assert again.hidden_by == er.RegistryEntryHider.INTEGRATION
