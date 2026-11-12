"""Opt-in device ownership for ecoMAX360i heat-pump installations."""

import math
import re
from typing import Any

from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.helpers import device_registry as dr

from .common_functions import is_ecomax360i_controller
from .const import BUFFER_PRESENCE_ABSENT, BUFFER_PRESENCE_PRESENT, DOMAIN


def _supported(data: dict[str, Any]) -> bool:
    """Limit the additional layout to the heat-pump protocol."""
    system = data.get("sysParams") or {}
    return (
        is_ecomax360i_controller(system.get("controllerID"))
        and system.get("protocolType") == "gm3_pomp"
    )


def _temperature(value: Any) -> bool:
    """Recognise connected temperature readings, including sub-zero values."""
    if value is None or isinstance(value, bool):
        return False
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value not in (999, 65535)


def _circuit_present(data: dict[str, Any], number: int) -> bool:
    """Require measured circuit data rather than unused parameter defaults."""
    registers = data.get("regParams") or {}
    if number == 1:
        return _temperature(registers.get("TempClutch")) or (
            _temperature(registers.get("Circuit1thermostat"))
            and float(registers["Circuit1thermostat"]) != 0
        )
    return _temperature(registers.get(f"TempCircuit{number}"))


_OUTDOOR_TEMPERATURES = (
    "AxenOutgoingTemp",
    "AxenReturnTemp",
    "AxenOutdoorTemp",
    "afterCompressorTemp",
    "beforeCompressorTemp",
    "exhaustGasTemp",
    "outdoorTemp",
)
_OUTDOOR_KEYS = {
    "ActualFlowTemp",
    "ActualReturnTemp",
    "TargetFlowTemp",
    "FanSpeed",
    "HeatPumpAmbient",
    "ElectricalPower",
    "ThermalPower",
    "COP",
    "SCOP",
    "FlowRate",
    "PeriodicEnergyConsumption",
    "ElectricPower",
    "HeatingPower",
    "CoolingPower",
    "currentFlow",
    "HeatSourceCalcPresetTemp",
    "flapValveStates",
}
_GATEWAY_KEYS = {
    "",
    "uid",
    "softVer",
    "hwVer",
    "signal",
    "quality",
    "routerType",
    "ecosrvSoftVer",
    "networkStatus",
    "connectionStatus",
}


def supported_components(data: dict[str, Any]) -> set[str]:
    """Discover hardware from readings/configuration, not dormant settings."""
    if not _supported(data):
        return set()
    registers = data.get("regParams") or {}
    editable = data.get("editParams") or {}
    components = {"gateway", "controller"}
    if any(_temperature(registers.get(key)) for key in _OUTDOOR_TEMPERATURES):
        components.add("heat_pump")
    for number in range(1, 8):
        if not _circuit_present(data, number):
            continue
        components.add(f"circuit_{number}")
        key = "Circuit1thermostat" if number == 1 else f"Circuit{number}thermostatTemp"
        value = registers.get(key)
        if _temperature(value) and float(value) != 0:
            components.add(f"thermostat_{number}")
    setpoint = editable.get("103") or {}
    if (
        _temperature(registers.get("TempCWU"))
        and setpoint.get("name") == "HDWTSetPoint"
    ):
        components.add("dhw")
    return components


def _candidate_component(key: str) -> str:
    """Classify protocol names without guessing the meaning of numeric IDs."""
    if key in _GATEWAY_KEYS or key.startswith("health-"):
        return "gateway"
    match = re.fullmatch(r"Circuit([1-7])thermostat(?:Temp)?", key, re.IGNORECASE)
    if match:
        return f"thermostat_{match[1]}"
    match = re.match(r"(?:Circuit|TempCircuit)([1-7])", key, re.IGNORECASE)
    if match:
        return f"circuit_{match[1]}"
    if key in ("TempClutch", "HeatDemanded"):
        return "circuit_1"
    if key.startswith(("HDW", "DHW")) or key in (
        "TempCWU",
        "ActualDHWTemp",
        "statusCWU",
        "cwuTZ",
        "water_heater",
    ):
        return "dhw"
    if (
        key.startswith(("Bufor", "Buffer", "TempBufor"))
        or key == "HPStatusBuffHeatStat"
    ):
        return "buffer"
    if (
        key.startswith(("Axen", "HPStatus", "ssa"))
        or key in _OUTDOOR_KEYS
        or key in _OUTDOOR_TEMPERATURES
    ):
        return "heat_pump"
    return "controller"


def component_for_key(
    data: dict[str, Any], key: str, components: set[str] | None = None
) -> str | None:
    """Return a supported owner, retaining unknown/unfitted values on the controller."""
    if not _supported(data):
        return None
    components = supported_components(data) if components is None else components
    candidate = _candidate_component(key)
    return candidate if candidate in components else "controller"


_CHILD_DEVICE_INFO = getattr(dr, "ChildDeviceInfo", None)
_SUPPORTS_VIA_DEVICE_ID = (MAJOR_VERSION, MINOR_VERSION) >= (2026, 8)
_DEVICE_NAMES = {
    "controller": ("Controller", "hp_controller"),
    "heat_pump": ("Heat pump outdoor unit", "hp_outdoor"),
    "dhw": ("DHW cylinder", "hp_dhw"),
    "buffer": ("Buffer", "hp_buffer"),
}


def _identifier(uid: str, component: str) -> str:
    """Reuse the existing DHW/buffer identifiers and stable indexed circuit IDs."""
    suffix = {"gateway": "", "dhw": "huw", "heat_pump": "heat-pump"}.get(
        component, component.replace("_", "-")
    )
    return f"{uid}-{suffix}" if suffix else uid


def _logical(component: str) -> bool:
    """Circuits and passive vessels are controller services, not extra controllers."""
    return component in ("dhw", "buffer") or component.startswith("circuit_")


def _child_component(component: str) -> bool:
    """Use children for new circuit groups, keeping legacy vessel devices reversible."""
    return component.startswith("circuit_")


def _device_info(coordinator: Any, api: Any, component: str) -> Any:
    """Build version-compatible physical or logical component metadata."""
    if component.startswith(("circuit_", "thermostat_")):
        number = component.rsplit("_", 1)[1]
        is_circuit = component.startswith("circuit_")
        name = (
            f"Heating circuit {number}" if is_circuit else f"Room thermostat {number}"
        )
        translation_key = "hp_circuit" if is_circuit else "hp_thermostat"
        placeholders = {"number": number}
    else:
        name, translation_key = _DEVICE_NAMES[component]
        placeholders = {}
    info = {
        "identifiers": {(DOMAIN, _identifier(api.uid, component))},
        "name": name,
        "translation_key": translation_key,
        "translation_placeholders": placeholders,
    }
    parent = "gateway" if component == "controller" else "controller"
    parent_id = coordinator.component_device_ids.get(parent)
    if _child_component(component) and _CHILD_DEVICE_INFO is not None:
        return _CHILD_DEVICE_INFO(parent_device_id=parent_id, **info)
    if _logical(component):
        info["entry_type"] = dr.DeviceEntryType.SERVICE
    elif component == "controller":
        system = coordinator.data.get("sysParams") or {}
        info.update(manufacturer="PLUM", model=system.get("controllerID"))
        if system.get("moduleASoftVer"):
            info["sw_version"] = system["moduleASoftVer"]
    if parent_id:
        if _SUPPORTS_VIA_DEVICE_ID:
            info["via_device_id"] = parent_id
        else:
            info["via_device"] = (DOMAIN, _identifier(api.uid, parent))
    return dr.DeviceInfo(**info)


def component_device_info(coordinator: Any, api: Any, key: str) -> Any | None:
    """Use the opt-in topology; None leaves the platform's legacy path intact."""
    if getattr(coordinator, "component_device_tree", False) is not True:
        return None
    data = coordinator.data or {}
    if not _supported(data):
        return None
    registered = getattr(coordinator, "component_device_ids", {})
    components = (
        set(registered) if isinstance(registered, dict) and registered else None
    )
    component = component_for_key(data, key, components)
    if component in (None, "gateway"):
        return None
    return _device_info(coordinator, api, component)


def edit_param_device_info(coordinator: Any, api: Any, param_id: str) -> Any | None:
    """Resolve editable controls by their reported name, never by guessing an ID."""
    data = coordinator.data or {}
    entry = (
        (data.get("editParamCatalog") or {}).get(param_id)
        or (data.get("editParams") or {}).get(param_id)
        or {}
    )
    return component_device_info(coordinator, api, entry.get("name", ""))


async def async_setup_component_devices(
    hass: Any, entry: Any, coordinator: Any, api: Any
) -> None:
    """Register the opted-in topology without removing devices or user metadata."""
    if getattr(
        coordinator, "component_device_tree", False
    ) is not True or not _supported(coordinator.data or {}):
        return
    registry = dr.async_get(hass)
    root = registry.async_get(coordinator.controller_device_id)
    if root is None:
        raise ValueError("Register the ecoNET gateway before its components")
    components = supported_components(coordinator.data)
    candidates = {"controller", "heat_pump", "dhw", "buffer"}
    candidates.update(
        f"{kind}_{number}"
        for kind in ("circuit", "thermostat")
        for number in range(1, 8)
    )
    existing = {}
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    child_entries = getattr(dr, "async_child_entries_for_config_entry", None)
    if child_entries is not None:
        devices += child_entries(registry, entry.entry_id)
    for device in devices:
        for component in candidates:
            if (DOMAIN, _identifier(api.uid, component)) in device.identifiers:
                existing[component] = device
    # Once discovered, a temporarily disconnected sensor must not move its entities.
    components.update(existing)
    if coordinator.buffer_presence == BUFFER_PRESENCE_PRESENT:
        components.add("buffer")
    elif coordinator.buffer_presence == BUFFER_PRESENCE_ABSENT:
        components.discard("buffer")
    coordinator.component_device_ids = {"gateway": root.id}
    for component in ["controller", *sorted(components - {"gateway", "controller"})]:
        info = _device_info(coordinator, api, component)
        # HA 2026.11 replaced the info TypedDicts with dataclasses.
        fields = info if isinstance(info, dict) else info.as_dict()
        # Translations are resolved when entities are added by their platforms.
        args = {
            key: value
            for key, value in fields.items()
            if key not in ("translation_key", "translation_placeholders")
        }
        if _child_component(component) and _CHILD_DEVICE_INFO is not None:
            device = registry.async_get_or_create_child(
                config_entry_id=entry.entry_id, **args
            )
        else:
            create_kwargs: dict[str, Any] = {}
            if component not in existing and root.disabled_by is not None:
                create_kwargs["disabled_by"] = root.disabled_by
            device = registry.async_get_or_create(
                config_entry_id=entry.entry_id, **create_kwargs, **args
            )
            if _logical(component):
                clear = {
                    field: None
                    for field in (
                        "manufacturer",
                        "model",
                        "model_id",
                        "sw_version",
                        "hw_version",
                        "serial_number",
                        "configuration_url",
                    )
                    if getattr(device, field, None) is not None
                }
                if clear:
                    device = registry.async_update_device(device.id, **clear)
        if (
            component not in existing
            and root.area_id
            and not (_child_component(component) and _CHILD_DEVICE_INFO is not None)
        ):
            device = registry.async_update_device(device.id, area_id=root.area_id)
        coordinator.component_device_ids[component] = device.id
