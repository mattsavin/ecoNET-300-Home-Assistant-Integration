"""Offline safety tests for raw edit parameter hiding."""

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock

from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import (
    RegistryEntryDisabler,
    RegistryEntryHider,
    async_get as async_get_entity_registry,
)
from homeassistant.helpers.storage import Store
import pytest
import pytest_asyncio

from custom_components.econet300.const import DOMAIN
from custom_components.econet300.raw_entity_hiding import (
    apply_raw_entity_hiding,
    preview_raw_entities,
)

CATALOG = {"500": {"name": "PumpPower", "kind": "number"}}


def _make_config_entry(entry_id: str, title: str = "ecoNET300") -> ConfigEntry:
    return ConfigEntry(
        data={},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        entry_id=entry_id,
        minor_version=1,
        options={},
        source=SOURCE_USER,
        subentries_data=None,
        title=title,
        unique_id=f"uid-{entry_id}",
        version=1,
    )


@pytest_asyncio.fixture
async def registry(hass, monkeypatch):
    """Load a real HA entity registry without reading or writing disk storage."""
    monkeypatch.setattr(Store, "async_load", AsyncMock(return_value=None))
    monkeypatch.setattr(Store, "async_delay_save", MagicMock())
    entity_registry = async_get_entity_registry(hass)
    await entity_registry.async_load()
    entries = {
        "entry1": _make_config_entry("entry1"),
        "other": _make_config_entry("other", "Other"),
    }
    hass.config_entries.async_get_entry.side_effect = entries.get
    hass.config_entries.async_entries.return_value = list(entries.values())
    entity_registry._entries = entries  # noqa: SLF001
    return entity_registry


def add_entry(registry, **changes):
    """Register a real HA entity registry entry."""
    values = {
        "domain": "number",
        "platform": DOMAIN,
        "unique_id": "controller-edit_500",
        "suggested_object_id": "pump_power",
        "original_name": "Pump power (500)",
        "config_entry_id": "entry1",
        "disabled_by": None,
        "hidden_by": None,
    }
    values.update(changes)
    config_entry_id = values.pop("config_entry_id")
    config_entry = registry._entries.get(config_entry_id) if config_entry_id else None  # noqa: SLF001
    return registry.async_get_or_create(
        values.pop("domain"),
        values.pop("platform"),
        values.pop("unique_id"),
        suggested_object_id=values.pop("suggested_object_id"),
        original_name=values.pop("original_name"),
        config_entry=config_entry,
        disabled_by=values.pop("disabled_by"),
        hidden_by=values.pop("hidden_by"),
    )


def test_preview_matches_catalog_without_mutation(registry):
    """Preview has no registry side effects."""
    entry = add_entry(registry)
    candidates = preview_raw_entities(registry, "entry1", "controller", CATALOG)
    assert [(item.entity_id, item.unique_id) for item in candidates] == [
        (entry.entity_id, "controller-edit_500")
    ]
    assert registry.async_get(entry.entity_id).hidden_by is None


@pytest.mark.parametrize(
    "changes",
    [
        {"config_entry_id": "other"},
        {"platform": "other"},
        {"hidden_by": RegistryEntryHider.USER},
        {"hidden_by": RegistryEntryHider.INTEGRATION},
        {"disabled_by": RegistryEntryDisabler.USER},
        {"original_name": "Other (500)"},
        {"original_name": None},
        {"unique_id": "controller-edit_500_extra"},
        {"unique_id": "other-edit_500"},
        {"domain": "select"},
    ],
)
def test_preview_excludes_unsafe_entries(registry, changes):
    """Entries failing any identity or visibility check are excluded."""
    add_entry(registry, **changes)
    assert preview_raw_entities(registry, "entry1", "controller", CATALOG) == []


@pytest.mark.parametrize("pid", ["103", "115", "119", "236", "238", "239"])
def test_protected_ids_never_preview(registry, pid):
    """Core control IDs are never offered."""
    add_entry(
        registry,
        unique_id=f"controller-edit_{pid}",
        original_name=f"Pump power ({pid})",
    )
    assert (
        preview_raw_entities(registry, "entry1", "controller", {pid: CATALOG["500"]})
        == []
    )


def test_select_and_secondary_number_are_supported(registry):
    """Both supported forms are recognized for multi-exposed parameters."""
    select = add_entry(registry, domain="select", unique_id="controller-edit_500")
    number = add_entry(
        registry,
        unique_id="controller-edit_500_value",
        original_name="Pump power (500) value",
    )
    catalog = {"500": {"name": "PumpPower", "kind": "select", "expose_number": True}}
    result = preview_raw_entities(registry, "entry1", "controller", catalog)
    assert {item.entity_id for item in result} == {select.entity_id, number.entity_id}


def test_legacy_untranslated_original_name_is_supported(registry):
    """Existing entries registered before friendly naming remain eligible."""
    entry = add_entry(
        registry,
        unique_id="controller-edit_113",
        original_name="HDWLoadTime (113)",
    )
    catalog = {"113": {"name": "HDWLoadTime", "kind": "number"}}
    result = preview_raw_entities(registry, "entry1", "controller", catalog)
    assert [item.entity_id for item in result] == [entry.entity_id]


def test_apply_revalidates_selection_and_only_hides(registry):
    """Only selected and unchanged entries are hidden, preserving customizations."""
    entry = add_entry(registry)
    registry.async_update_entity(entry.entity_id, name="Custom pump name")
    selected = preview_raw_entities(registry, "entry1", "controller", CATALOG)
    applied, skipped = apply_raw_entity_hiding(
        registry, "entry1", "controller", CATALOG, selected
    )
    assert applied == [entry.entity_id]
    assert skipped == []
    updated = registry.async_get(entry.entity_id)
    assert updated.hidden_by == RegistryEntryHider.INTEGRATION
    assert updated.disabled_by is None
    assert updated.name == "Custom pump name"

    registry.async_update_entity(entry.entity_id, new_unique_id="replacement")
    applied, skipped = apply_raw_entity_hiding(
        registry, "entry1", "controller", CATALOG, selected
    )
    assert applied == []
    assert skipped == [entry.entity_id]


@pytest.mark.parametrize("change", ["hidden", "disabled", "name", "deleted", "catalog"])
def test_apply_skips_changed_candidates(registry, change):
    """Revalidation rejects changes occurring after preview."""
    entry = add_entry(registry)
    selected = preview_raw_entities(registry, "entry1", "controller", CATALOG)
    catalog = CATALOG
    if change == "deleted":
        registry.async_remove(entry.entity_id)
    elif change == "catalog":
        catalog = {"500": {"name": "OtherName", "kind": "number"}}
    elif change == "hidden":
        registry.async_update_entity(entry.entity_id, hidden_by=RegistryEntryHider.USER)
    elif change == "disabled":
        registry.async_update_entity(
            entry.entity_id, disabled_by=RegistryEntryDisabler.USER
        )
    elif change == "name":
        registry.async_update_entity(entry.entity_id, original_name="Changed")

    assert apply_raw_entity_hiding(
        registry, "entry1", "controller", catalog, selected
    ) == ([], [entry.entity_id])
    current = registry.async_get(entry.entity_id)
    if change != "deleted":
        assert current.hidden_by != RegistryEntryHider.INTEGRATION


def test_apply_continues_and_reports_partial_failure(registry, monkeypatch):
    """A single update failure does not mask earlier or later entries."""
    first = add_entry(registry, unique_id="controller-edit_500")
    second = add_entry(
        registry,
        unique_id="controller-edit_501",
        suggested_object_id="other_param",
        original_name="Other param (501)",
    )
    third = add_entry(
        registry,
        unique_id="controller-edit_502",
        suggested_object_id="third_param",
        original_name="Third param (502)",
    )
    catalog = {
        "500": {"name": "PumpPower", "kind": "number"},
        "501": {"name": "OtherParam", "kind": "number"},
        "502": {"name": "ThirdParam", "kind": "number"},
    }
    selected = preview_raw_entities(registry, "entry1", "controller", catalog)
    real_update = registry.async_update_entity

    def fail_second(entity_id, **kwargs):
        if entity_id == second.entity_id:
            raise RuntimeError("boom")
        return real_update(entity_id, **kwargs)

    monkeypatch.setattr(registry, "async_update_entity", fail_second)
    applied, skipped = apply_raw_entity_hiding(
        registry, "entry1", "controller", catalog, selected
    )
    assert applied == [first.entity_id, third.entity_id]
    assert skipped == [second.entity_id]
    assert (
        registry.async_get(first.entity_id).hidden_by == RegistryEntryHider.INTEGRATION
    )
    assert registry.async_get(second.entity_id).hidden_by is None
    assert (
        registry.async_get(third.entity_id).hidden_by == RegistryEntryHider.INTEGRATION
    )
    assert er.async_entries_for_config_entry(registry, "entry1")
