"""Conservative preview and hiding of existing raw edit-parameter entities."""

from dataclasses import dataclass
import logging
import re
from typing import Any

from homeassistant.helpers.entity_registry import (
    EntityRegistry,
    RegistryEntry,
    RegistryEntryHider,
    async_entries_for_config_entry,
)

from .common_functions import friendly_edit_param_name
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_PROTECTED_PIDS = frozenset({"103", "115", "119", "236", "238", "239"})
_RAW_DOMAINS = frozenset({"number", "select", "switch"})
RAW_CATEGORY_ORDER = (
    "bitmasks",
    "service_registers",
    "unused_mixers",
    "duplicate_values",
    "other",
)
_UNUSED_MIXER_RE = re.compile(r"^(?:Mixer|Mix)[2-7]", re.IGNORECASE)
_SERVICE_REGISTER_RE = re.compile(
    r"^(?:FactorySetup|Ere?aseEnergy|Axenregister|HoldingRegister|Hfanspeed|"
    r"ahs(?:Pump|Temp)|Axen2155|UhsPump|PwmInverse|ScreedDrying|EPowerWorldRegisters)",
    re.IGNORECASE,
)
_BITMASK_NAME_RE = re.compile(r"(?:Settings|Sett)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RawEntityCandidate:
    """A preview identity, to be explicitly selected by a caller."""

    entity_id: str
    unique_id: str
    param_id: str
    catalog_name: str


def classify_raw_candidate(
    candidate: RawEntityCandidate, info: dict[str, Any] | None = None
) -> str:
    """Bucket a raw edit-parameter candidate into a compact review category."""
    if candidate.unique_id.endswith("_value"):
        return "duplicate_values"
    name = candidate.catalog_name
    if _UNUSED_MIXER_RE.match(name):
        return "unused_mixers"
    if _SERVICE_REGISTER_RE.match(name):
        return "service_registers"
    if (
        isinstance(info, dict)
        and info.get("kind") == "number"
        and _BITMASK_NAME_RE.search(name)
    ):
        return "bitmasks"
    return "other"


def group_raw_candidates(
    candidates: list[RawEntityCandidate],
    catalog: dict[str, dict[str, Any]],
) -> dict[str, list[RawEntityCandidate]]:
    """Group candidates by category, omitting empty categories in stable order."""
    buckets: dict[str, list[RawEntityCandidate]] = {
        key: [] for key in RAW_CATEGORY_ORDER
    }
    for candidate in candidates:
        category = classify_raw_candidate(candidate, catalog.get(candidate.param_id))
        buckets[category].append(candidate)
    return {key: items for key, items in buckets.items() if items}


def _match_candidate(
    entry: RegistryEntry,
    config_entry_id: str,
    uid: str,
    catalog_by_unique_id: dict[str, tuple[str, dict[str, Any], bool]],
) -> RawEntityCandidate | None:
    """Match a single registry entry against the expected raw edit-param shape."""
    if entry.config_entry_id != config_entry_id or entry.platform != DOMAIN:
        return None
    if entry.hidden_by is not None or entry.disabled_by is not None:
        return None
    domain = entry.entity_id.partition(".")[0]
    if domain not in _RAW_DOMAINS:
        return None
    match = catalog_by_unique_id.get(entry.unique_id)
    if match is None:
        return None
    pid, info, suffix = match
    kind = info.get("kind")
    if domain != kind and not suffix:
        return None
    name = info.get("name")
    if not isinstance(name, str):
        return None
    expected_name = f"{friendly_edit_param_name(name)} ({pid})"
    if suffix:
        expected_name += " value"
    raw_fallback = f"{name} ({pid})" + (" value" if suffix else "")
    if entry.original_name not in (expected_name, raw_fallback):
        return None
    return RawEntityCandidate(entry.entity_id, entry.unique_id, pid, name)


def _index_catalog(
    uid: str, catalog: dict[str, dict[str, Any]]
) -> dict[str, tuple[str, dict[str, Any], bool]]:
    """Index eligible editParams catalog entries by expected unique_id."""
    index: dict[str, tuple[str, dict[str, Any], bool]] = {}
    for pid, info in catalog.items():
        if (
            not isinstance(pid, str)
            or not pid.isdigit()
            or not isinstance(info, dict)
            or pid in _PROTECTED_PIDS
        ):
            continue
        name = info.get("name")
        if not isinstance(name, str) or not name or name == f"Param {pid}":
            continue
        base = f"{uid}-edit_{pid}"
        index[base] = (pid, info, False)
        if info.get("kind") != "number" and bool(info.get("expose_number")):
            index[f"{base}_value"] = (pid, info, True)
    return index


def preview_raw_entities(
    registry: EntityRegistry,
    config_entry_id: str,
    uid: str,
    catalog: dict[str, dict[str, Any]],
) -> list[RawEntityCandidate]:
    """Return eligible entries without changing or selecting anything."""
    catalog_index = _index_catalog(uid, catalog)
    result = []
    for entry in async_entries_for_config_entry(registry, config_entry_id):
        candidate = _match_candidate(entry, config_entry_id, uid, catalog_index)
        if candidate is not None:
            result.append(candidate)
    return result


def apply_raw_entity_hiding(
    registry: EntityRegistry,
    config_entry_id: str,
    uid: str,
    catalog: dict[str, dict[str, Any]],
    selected: list[RawEntityCandidate],
) -> tuple[list[str], list[str]]:
    """Hide only explicit, still-eligible preview identities; return applied/skipped IDs."""
    catalog_index = _index_catalog(uid, catalog)
    applied: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for candidate in selected:
        current = registry.async_get(candidate.entity_id)
        if (
            candidate.entity_id in seen
            or current is None
            or current.unique_id != candidate.unique_id
            or _match_candidate(current, config_entry_id, uid, catalog_index)
            != candidate
        ):
            skipped.append(candidate.entity_id)
            continue
        seen.add(candidate.entity_id)
        try:
            registry.async_update_entity(
                candidate.entity_id, hidden_by=RegistryEntryHider.INTEGRATION
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to hide raw entity %s", candidate.entity_id, exc_info=True
            )
            skipped.append(candidate.entity_id)
        else:
            applied.append(candidate.entity_id)
    return applied, skipped
