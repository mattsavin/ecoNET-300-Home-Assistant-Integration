# Configuration Options

After the integration is set up, you can change its options from Home Assistant:

```text
Settings > Devices & services > ecoNET300 > Configure
```

## Available Options

- **Connection Settings** - update the local ecoNET300 host, username, or password.
- **Polling settings** - adjust how often the integration refreshes data from the controller.
- **Device settings** - choose how entities are grouped into Home Assistant devices.
- **Custom Entities** - expose additional parameters discovered from your controller.
- **Generate diagnostics report** - create a redacted diagnostics report for troubleshooting or GitHub issues.

## Polling Settings

Use **Polling settings** when you want to change how often Home Assistant reads data from the controller.

| Option | Default | Range | Description |
| ------ | ------- | ----- | ----------- |
| `regParams` polling interval | 15 seconds | 5-300 seconds | Live sensor values, such as temperatures, pumps, fans, and statuses. |
| `sysParams` polling interval | 300 seconds | 10-3600 seconds | Controller metadata and system information. |
| `editParams` polling interval | 300 seconds | 0-3600 seconds | Editable parameters (ecoMAX360i) and ecoSTER setpoints. Use `0` to disable periodic polling. See [ecoSTER setpoints](ENTITIES.md#ecoster-room-thermostat-setpoints) for modules without `editParams`. |

For better graph granularity, reduce the **regParams polling interval**. This controls the live sensor values shown in Home Assistant history graphs.

The minimum for live polling is **5 seconds**.

## Connection Settings

Use **Connection Settings** to update the local device connection details without removing and re-adding the integration.

- **Host** - local IP address or hostname of the ecoNET300 module.
- **Username** - local ecoNET300 username.
- **Password** - local ecoNET300 password.

These are local device credentials, not econet24.com cloud credentials.

## When the Device Is Offline

When the ecoNET300 module does not answer, for example after a power cut or a network problem:

- The log shows one line when the module stops answering, `Device <host> is unavailable: <reason>`, and one
  when it answers again, `Device <host> is available again after <N> failed updates`. Both are at `info` level,
  as the Home Assistant [log-when-unavailable](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/log-when-unavailable)
  rule asks. The failed updates in between are logged at `debug` level only.
- Entities keep their last values for 10 minutes, so a short outage does not interrupt graphs. After that they
  become **Unavailable**. The diagnostic *Live polling* binary sensor and the *Consecutive failures* and
  *Data age* sensors show the connection state right away.
- After 5 failed updates in a row, **Settings → System → Repairs** shows *Connection to ecoNET300 device failed*.
  It disappears when the module answers again.
- If the module answers `regParams` without data, the integration asks once more after 1 second before the
  update counts as failed.

## Device Settings

Use **Device settings** to choose how Home Assistant groups entities:

- **Split (default)** - keep the existing separate devices for boiler, mixers, lambda, ecoSTER, and other components.
- **Single** - expose all entities under one merged ecoNET300 device.
- **Heat pump components (opt-in)** (`components`) - separate supported physical devices from logical
  heating groups on **ecoMAX360i controllers using `gm3_pomp` only**. Other controllers keep their existing layout.

Split and Single retain their existing behaviour; component mode is never enabled automatically.
Select **Heat pump components (opt-in)** in this menu and save to enable it.

In the same menu, choose **Separate buffer group** or **No separate buffer group**. The default
**Unknown** preserves an existing buffer group but does not create a new one. This setting changes
device grouping, not the controller's hydraulic configuration, and does not establish that any
buffer-labelled readings correspond to a dedicated sensor.

### Heating circuit selection

For supported ecoMAX360i controllers using `gm3_pomp`, **Heating circuits to expose** selects circuits
1–7 independently of device grouping. All circuits are selected by default, including on existing installs.
An empty selection excludes entities that can be identified as belonging to a circuit; entities with unknown or
ambiguous sources remain. The selection does not detect whether a circuit is physically present.
Save to reload the integration. Excluded circuit entities and devices remain in the registry; existing entities
may become unavailable. Re-select a circuit to expose its supported entities again. Check automations and
dashboards that use excluded entities, and review any unused registry entries before removing them manually.

### Heat pump component layout

The existing ecoNET300 device remains the gateway. A separate PLUM controller owns controller diagnostics
and unclassified controls; outdoor-unit telemetry and measured room thermostats get their own physical
device groups when supported. Heating circuits, the DHW cylinder and the buffer are logical groups under
the controller, not additional independently identified controllers.

On Home Assistant 2026.9 or newer, **heating circuits only** use the child-device API when available. On older
supported versions circuits are ordinary service-type devices linked to the controller. **DHW and buffer always
remain ordinary service-type devices**, reusing their existing identifiers so switching back to Split is reversible.
No minimum Home Assistant version increase is required. The layout does not establish an outdoor-unit brand/model
or a thermostat serial number.
See [component ownership and capability gates](ENTITIES.md#heat-pump-component-ownership) for what is grouped
and the evidence required before creating each group.

**Before changing mode, review device-targeted automations and areas.** Entity IDs, unique IDs, history and
user overrides are preserved, but device membership and hierarchy change; generated friendly names may change.
Keeping the original gateway device does not preserve its former entity membership. The same review is needed
when changing back to Single or Split, including with the older-Home-Assistant fallback. Automations are not
rewritten automatically. Existing device names and areas are retained; newly created ordinary devices initially
copy the gateway area once and may need reassignment. Native circuit children follow their parent hierarchy;
DHW and buffer do not gain child-device target or area inheritance.
See [migration safeguards](MIGRATION.md#heat-pump-components-opt-in) before opting in.

## Custom Entities

Use **Custom Entities** to expose additional parameters discovered from your controller that are not included by default.

The flow lets you:

- Choose an API endpoint to browse.
- Select parameters available on your controller.
- Configure the entity name, device group, entity type, category, unit, device class, and precision where applicable.

## Diagnostics Report

Use **Generate diagnostics report** when opening a GitHub issue or troubleshooting a controller-specific problem.

The action creates a redacted diagnostics report and writes it to `homeassistant.log` with the marker:

```text
ECONET300_DIAGNOSTICS_REPORT
```

Attach the matching log block or the standard Home Assistant diagnostics download when reporting an issue.

## Newly discovered raw parameter visibility

In **Device settings**, **Hide newly discovered raw parameters** is off by default.
When enabled, newly registered generic editable parameter number, select and switch
entities are hidden by default in Home Assistant; this option does not disable them, and they can be
shown in the entity registry. This applies in every device grouping mode. Existing
registry entries and their visibility choices are not changed when the option is
toggled. Entity IDs and automations are unaffected; no bulk migration is performed.

## Hiding existing raw parameters

Use **Configure → Hide existing raw parameters** to review visible generic editable
number, select and switch entities grouped by category and hide selected groups explicitly.

- Nothing is pre-selected; changes apply only after reviewing the exact entity list and confirming.
- Core DHW and Circuit 1 controls, custom entities, already-hidden entries and disabled entries are excluded from selection.
- Hiding does not disable entities or remove them from automations.
- Home Assistant records only `hidden_by=integration` without an integration undo log; unhide individual entities from Home Assistant's entity registry if needed.
