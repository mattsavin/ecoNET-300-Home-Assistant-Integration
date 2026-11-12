"""Registry-backed regression tests for opting into component devices."""

from copy import deepcopy
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.config_entries import ConfigEntry, SOURCE_USER
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.storage import Store
import pytest
import pytest_asyncio

from custom_components.econet300 import device_grouping
from custom_components.econet300.common import (
    EconetDataCoordinator,
    build_edit_param_catalog,
)
from custom_components.econet300.const import (
    CONF_DEVICE_GROUPING,
    DEVICE_GROUPING_SINGLE,
    DEVICE_GROUPING_SPLIT,
    DOMAIN,
)
from custom_components.econet300.number import EditParamNumber
from custom_components.econet300.sensor import (
    EconetSensor,
    EconetSensorEntityDescription,
)


@pytest_asyncio.fixture
async def migration(hass, monkeypatch, load_fixture):
    """Load real HA registries without reading or scheduling storage writes."""
    monkeypatch.setattr(Store, "async_load", AsyncMock(return_value=None))
    monkeypatch.setattr(Store, "async_delay_save", MagicMock())
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    areas = ar.async_get(hass)
    for registry in (devices, entities, areas):
        await registry.async_load()

    entry = ConfigEntry(
        data={},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        entry_id="component-migration-entry",
        minor_version=1,
        options={},
        source=SOURCE_USER,
        subentries_data=None,
        title="Heating",
        unique_id="migration-uid",
        version=1,
    )
    hass.config_entries.async_get_entry.side_effect = lambda entry_id: (
        entry if entry_id == entry.entry_id else None
    )
    hass.config_entries.async_entries.return_value = [entry]
    api = SimpleNamespace(
        uid="migration-uid",
        model_id="ecoMAX360i",
        host="http://192.0.2.1",
        sw_rev="3.2.3881",
        hw_ver="mr3020-v3",
    )
    registers = load_fixture("ecoMAX360-cf8", "regParams.json")
    editable = load_fixture("ecoMAX360-cf8", "editParams.json")
    data = {
        "sysParams": load_fixture("ecoMAX360-cf8", "sysParams.json"),
        "regParams": registers.get("curr", registers),
        "regParamsSchema": registers["schemaParams"],
        "editParams": editable["data"],
        "editParamsFull": editable,
        "editParamCatalog": build_edit_param_catalog(editable),
    }
    root = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, api.uid)},
        name="PLUM ecoNET300",
        manufacturer="PLUM",
        model="ecoNET300",
        model_id=api.model_id,
        sw_version=api.sw_rev,
        hw_version=api.hw_ver,
    )
    plant_room = areas.async_create("Plant room")
    living_room = areas.async_create("Living room")
    root = devices.async_update_device(
        root.id, area_id=plant_room.id, name_by_user="My heating gateway"
    )
    await hass.async_block_till_done()
    return SimpleNamespace(
        hass=hass,
        entry=entry,
        api=api,
        data=data,
        devices=devices,
        entities=entities,
        root=root,
        plant_room=plant_room.id,
        living_room=living_room.id,
    )


def _coordinator(migration, mode="components", buffer_presence="unknown"):
    """Create the same fresh coordinator an integration reload would use."""
    coordinator = EconetDataCoordinator(
        migration.hass,
        migration.api,
        migration.entry,
        options={CONF_DEVICE_GROUPING: mode, "buffer_presence": buffer_presence},
    )
    coordinator.data = deepcopy(migration.data)
    coordinator.controller_device_id = migration.root.id
    return coordinator


def _entity(migration, coordinator, key):
    """Use the platform's actual unique-id implementation when re-registering."""
    if key == "Circuit1ComfortTemp":
        return EditParamNumber(coordinator, migration.api, "238")
    return EconetSensor(
        EconetSensorEntityDescription(key=key), coordinator, migration.api
    )


def _readd(migration, coordinator, key):
    """Exercise HA's device/entity get-or-create path with the new DeviceInfo."""
    info = device_grouping.component_device_info(coordinator, migration.api, key)
    assert info is not None
    device = migration.devices.async_get_or_create(
        config_entry_id=migration.entry.entry_id, **info
    )
    entity = _entity(migration, coordinator, key)
    domain = "number" if key == "Circuit1ComfortTemp" else "sensor"
    return migration.entities.async_get_or_create(
        domain,
        DOMAIN,
        entity.unique_id,
        config_entry=migration.entry,
        device_id=device.id,
        suggested_object_id=f"new_component_{key}",
        original_name="Component-provided name",
    )


@pytest.mark.asyncio
async def test_modern_child_registration_uses_supported_registry_api(
    migration, monkeypatch
):
    """A modern registry exposes async_get_or_create_child, not the old mock name."""
    monkeypatch.setattr(device_grouping, "_CHILD_DEVICE_INFO", lambda **kw: kw)
    children = []

    def create_child(*, config_entry_id, parent_device_id, identifiers, name):
        children.append((parent_device_id, identifiers))
        return migration.devices.async_get_or_create(
            config_entry_id=config_entry_id, identifiers=identifiers, name=name
        )

    monkeypatch.setattr(
        migration.devices, "async_get_or_create_child", create_child, raising=False
    )
    coordinator = _coordinator(migration)
    await device_grouping.async_setup_component_devices(
        migration.hass, migration.entry, coordinator, migration.api
    )
    assert children
    assert children[0][0] == coordinator.component_device_ids["controller"]
    assert "circuit_1" in coordinator.component_device_ids


@pytest.mark.asyncio
async def test_existing_child_survives_temporarily_missing_readings(
    migration, monkeypatch
):
    """An existing child must stay registered when its circuit reading disappears."""
    child = SimpleNamespace(
        identifiers={(DOMAIN, f"{migration.api.uid}-circuit-1")}, id="child-id"
    )
    monkeypatch.setattr(
        dr,
        "async_child_entries_for_config_entry",
        lambda registry, entry_id: [child],
        raising=False,
    )
    monkeypatch.setattr(device_grouping, "_CHILD_DEVICE_INFO", lambda **kw: kw)
    monkeypatch.setattr(
        migration.devices,
        "async_get_or_create_child",
        lambda **kw: child,
        raising=False,
    )
    coordinator = _coordinator(migration)
    coordinator.data["regParams"]["TempClutch"] = 999
    coordinator.data["regParams"]["Circuit1thermostat"] = 999
    await device_grouping.async_setup_component_devices(
        migration.hass, migration.entry, coordinator, migration.api
    )
    assert coordinator.component_device_ids["circuit_1"] == child.id


@pytest.mark.asyncio
async def test_confirmed_no_buffer_moves_entities_without_deleting_device(migration):
    """User-confirmed absence overrides retention while preserving identities."""
    old = migration.devices.async_get_or_create(
        config_entry_id=migration.entry.entry_id,
        identifiers={(DOMAIN, f"{migration.api.uid}-buffer")},
        name="Buffer",
    )
    original = migration.entities.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{migration.api.uid}-TempBuforDown",
        config_entry=migration.entry,
        device_id=old.id,
    )
    original = migration.entities.async_update_entity(
        original.entity_id, name="My buffer sensor", area_id=migration.living_room
    )
    migration.data["regParamsSchema"] = {"Bufor": [[], False, True]}
    coordinator = _coordinator(migration, buffer_presence="absent")
    await device_grouping.async_setup_component_devices(
        migration.hass, migration.entry, coordinator, migration.api
    )
    assert "buffer" not in coordinator.component_device_ids
    updated = _readd(migration, coordinator, "TempBuforDown")
    assert updated.id == original.id
    assert updated.unique_id == original.unique_id
    assert updated.name == original.name
    assert updated.area_id == original.area_id
    assert updated.device_id == coordinator.component_device_ids["controller"]
    assert migration.devices.async_get(old.id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("schema", [None, {}, {"Bufor": []}, {"Bufor": [[], False]}])
async def test_unknown_schematic_preserves_existing_buffer(migration, schema):
    """Missing or malformed flags do not detach a previously registered device."""
    old = migration.devices.async_get_or_create(
        config_entry_id=migration.entry.entry_id,
        identifiers={(DOMAIN, f"{migration.api.uid}-buffer")},
        name="Buffer",
    )
    migration.data["regParamsSchema"] = schema
    coordinator = _coordinator(migration)
    await device_grouping.async_setup_component_devices(
        migration.hass, migration.entry, coordinator, migration.api
    )
    assert coordinator.component_device_ids["buffer"] == old.id


@pytest.mark.asyncio
async def test_confirmed_buffer_creates_a_device_without_schematic(migration):
    """A user-confirmed buffer can be grouped without schematic data."""
    migration.data["regParamsSchema"] = None
    coordinator = _coordinator(migration, buffer_presence="present")
    await device_grouping.async_setup_component_devices(
        migration.hass, migration.entry, coordinator, migration.api
    )
    assert "buffer" in coordinator.component_device_ids


@pytest.mark.asyncio
async def test_component_reassignment_preserves_entity_registry_customizations(
    migration,
):
    """Moving ownership must not replace identities or override user settings."""
    cases = (
        ("Circuit1thermostat", "sensor", "Circuit1thermostat", "thermostat-1", None),
        (
            "Circuit1ComfortTemp",
            "number",
            "edit_238",
            "circuit-1",
            er.RegistryEntryDisabler.USER,
        ),
        ("TempCWU", "sensor", "TempCWU", "huw", er.RegistryEntryDisabler.INTEGRATION),
    )
    original = {}
    for key, domain, suffix, _, disabled_by in cases:
        entity = migration.entities.async_get_or_create(
            domain,
            DOMAIN,
            f"{migration.api.uid}-{suffix}",
            config_entry=migration.entry,
            device_id=migration.root.id,
            suggested_object_id=f"my_existing_{key}",
            disabled_by=disabled_by,
        )
        original[key] = migration.entities.async_update_entity(
            entity.entity_id,
            name=f"My {key}",
            area_id=migration.living_room,
        )
    await migration.hass.async_block_till_done()

    for _ in range(2):
        coordinator = _coordinator(migration)
        await device_grouping.async_setup_component_devices(
            migration.hass, migration.entry, coordinator, migration.api
        )
        await migration.hass.async_block_till_done()
        for key, _, _, device_suffix, _ in cases:
            updated = _readd(migration, coordinator, key)
            before = original[key]
            assert updated.entity_id == before.entity_id
            assert updated.unique_id == before.unique_id
            assert updated.id == before.id
            assert updated.name == before.name
            assert updated.area_id == before.area_id
            assert updated.disabled_by == before.disabled_by
            device = migration.devices.async_get(updated.device_id)
            assert device.identifiers == {
                (DOMAIN, f"{migration.api.uid}-{device_suffix}")
            }
        await migration.hass.async_block_till_done()
        for before in original.values():
            assert (
                migration.entities.async_get(before.entity_id).disabled_by
                == before.disabled_by
            )
        assert len(migration.entities.entities) == len(cases)
        assert migration.entities.deleted_entities == {}
        root = migration.devices.async_get(migration.root.id)
        assert root.identifiers == {(DOMAIN, migration.api.uid)}
        assert root.area_id == migration.plant_room
        assert root.name_by_user == "My heating gateway"


@pytest.mark.asyncio
async def test_fallback_area_copy_preserves_existing_component_area(migration):
    """New fallback groups inherit the old area; existing assignments win."""
    thermostat = migration.devices.async_get_or_create(
        config_entry_id=migration.entry.entry_id,
        identifiers={(DOMAIN, f"{migration.api.uid}-thermostat-1")},
        name="Room thermostat",
    )
    migration.devices.async_update_device(
        thermostat.id,
        area_id=migration.living_room,
        name_by_user="Hall thermostat",
    )
    coordinator = _coordinator(migration)
    await device_grouping.async_setup_component_devices(
        migration.hass, migration.entry, coordinator, migration.api
    )
    for key, expected_area in (
        ("Circuit1thermostat", migration.living_room),
        ("Circuit1ComfortTemp", migration.plant_room),
        ("TempCWU", migration.plant_room),
    ):
        updated = _readd(migration, coordinator, key)
        device = migration.devices.async_get(updated.device_id)
        assert device.area_id == expected_area
    preserved = migration.devices.async_get(thermostat.id)
    assert preserved.name_by_user == "Hall thermostat"
    assert preserved.area_id == migration.living_room


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffix", "key"), [("huw", "TempCWU"), ("buffer", "TempBuforUp")]
)
async def test_reused_logical_fallback_clears_controller_metadata(
    migration, suffix, key
):
    """Legacy tank UUIDs and user settings survive removal of fake hardware data."""
    old = migration.devices.async_get_or_create(
        config_entry_id=migration.entry.entry_id,
        identifiers={(DOMAIN, f"{migration.api.uid}-{suffix}")},
        name="Legacy component",
        manufacturer="PLUM",
        model="ecoNET300",
        model_id=migration.api.model_id,
        sw_version=migration.api.sw_rev,
        hw_version=migration.api.hw_ver,
        configuration_url=migration.api.host,
        via_device=(DOMAIN, migration.api.uid),
    )
    migration.devices.async_update_device(
        old.id,
        area_id=migration.living_room,
        name_by_user="My cylinder" if suffix == "huw" else "My buffer",
        disabled_by=dr.DeviceEntryDisabler.USER,
    )
    # This migration test explicitly models an installed buffer, not its defaults.
    if suffix == "buffer":
        migration.data["regParamsSchema"]["Bufor"][1] = True
        migration.data["regParams"]["TempBuforUp"] = 35.0
        migration.data["regParams"]["TempBuforDown"] = 30.0
    coordinator = _coordinator(
        migration, buffer_presence="present" if suffix == "buffer" else "unknown"
    )
    await device_grouping.async_setup_component_devices(
        migration.hass, migration.entry, coordinator, migration.api
    )
    info = device_grouping.component_device_info(coordinator, migration.api, key)
    assert info is not None
    updated = migration.devices.async_get_or_create(
        config_entry_id=migration.entry.entry_id, **info
    )
    assert updated.id == old.id
    assert updated.area_id == migration.living_room
    assert updated.name_by_user == ("My cylinder" if suffix == "huw" else "My buffer")
    assert updated.disabled_by is dr.DeviceEntryDisabler.USER
    assert updated.entry_type is dr.DeviceEntryType.SERVICE
    for field in (
        "manufacturer",
        "model",
        "model_id",
        "sw_version",
        "hw_version",
        "configuration_url",
    ):
        assert getattr(updated, field) is None
    controller = migration.devices.async_get_device(
        identifiers={(DOMAIN, f"{migration.api.uid}-controller")}
    )
    assert controller is not None
    assert updated.via_device_id == controller.id
    assert migration.devices.deleted_devices == {}


@pytest.mark.asyncio
async def test_disabled_root_keeps_device_disabled_entities_disabled(migration):
    """An ownership change must not re-enable entities disabled with the root."""
    entity = migration.entities.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{migration.api.uid}-Circuit1thermostat",
        config_entry=migration.entry,
        device_id=migration.root.id,
    )
    migration.devices.async_update_device(
        migration.root.id, disabled_by=dr.DeviceEntryDisabler.USER
    )
    await migration.hass.async_block_till_done()
    assert (
        migration.entities.async_get(entity.entity_id).disabled_by
        is er.RegistryEntryDisabler.DEVICE
    )
    coordinator = _coordinator(migration)
    await device_grouping.async_setup_component_devices(
        migration.hass, migration.entry, coordinator, migration.api
    )
    await migration.hass.async_block_till_done()
    updated = _readd(migration, coordinator, "Circuit1thermostat")
    await migration.hass.async_block_till_done()
    assert updated.id == entity.id
    assert (
        migration.entities.async_get(entity.entity_id).disabled_by
        is er.RegistryEntryDisabler.DEVICE
    )
    assert (
        migration.devices.async_get(migration.root.id).disabled_by
        is dr.DeviceEntryDisabler.USER
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [DEVICE_GROUPING_SINGLE, DEVICE_GROUPING_SPLIT])
async def test_leaving_component_mode_retains_existing_devices(migration, mode):
    """Reloads and opting back out must never delete or recreate device entries."""
    coordinator = _coordinator(migration)
    await device_grouping.async_setup_component_devices(
        migration.hass, migration.entry, coordinator, migration.api
    )
    before = dict(migration.devices.devices)
    assert len(before) > 1
    for grouping in ("components", mode, "components"):
        coordinator = _coordinator(migration, grouping)
        await device_grouping.async_setup_component_devices(
            migration.hass, migration.entry, coordinator, migration.api
        )
        assert set(migration.devices.devices) == set(before)
        for device_id, old in before.items():
            assert migration.devices.async_get(device_id).identifiers == old.identifiers
        assert migration.devices.deleted_devices == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [DEVICE_GROUPING_SPLIT, DEVICE_GROUPING_SINGLE])
async def test_legacy_layout_does_not_opt_into_component_devices(migration, mode):
    """The existing Split default is not permission to migrate the registry."""
    coordinator = _coordinator(migration, mode)
    await device_grouping.async_setup_component_devices(
        migration.hass, migration.entry, coordinator, migration.api
    )
    assert set(migration.devices.devices) == {migration.root.id}
    for key in ("Circuit1thermostat", "Circuit1ComfortTemp", "TempCWU"):
        assert (
            device_grouping.component_device_info(coordinator, migration.api, key)
            is None
        )
    assert migration.devices.deleted_devices == {}
