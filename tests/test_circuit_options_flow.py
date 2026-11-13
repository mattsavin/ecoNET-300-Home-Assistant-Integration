"""Device settings circuit selection options."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import voluptuous as vol

from custom_components.econet300.config_flow import EconetOptionsFlowHandler


@pytest.mark.asyncio
async def test_circuit_selection_defaults_saves_and_reopens():
    """The form defaults to all circuits and preserves a saved empty selection."""
    handler = EconetOptionsFlowHandler()
    handler.hass = MagicMock()
    handler.async_show_form = MagicMock(return_value={"type": "form"})
    handler.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    entry = MagicMock(options={"other": "kept"}, entry_id="e1")
    with patch.object(
        EconetOptionsFlowHandler, "config_entry", new_callable=PropertyMock
    ) as config:
        config.return_value = entry
        await handler.async_step_device_settings()
        schema = handler.async_show_form.call_args.kwargs["data_schema"]
        assert schema({})["selected_circuits"] == list("1234567")
        submitted = schema({"selected_circuits": []})
        await handler.async_step_device_settings(submitted)
        saved = handler.async_create_entry.call_args.kwargs["data"]
        assert saved["selected_circuits"] == []
        assert saved["other"] == "kept"
        handler.hass.config_entries.async_reload.assert_called_once_with("e1")
        entry.options = saved
        await handler.async_step_device_settings()
        reopened = handler.async_show_form.call_args.kwargs["data_schema"]
        assert reopened({})["selected_circuits"] == []
        assert reopened({"selected_circuits": ["1", "7"]})["selected_circuits"] == [
            "1",
            "7",
        ]
        for invalid in (["0"], ["8"], [1], "1"):
            with pytest.raises(vol.Invalid):
                reopened({"selected_circuits": invalid})
