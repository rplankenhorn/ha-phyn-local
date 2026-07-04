# Phyn Plus — Local JNAP Protocol

The Phyn Plus exposes a local **JNAP HTTP API on port 80** of the LAN. It requires no cloud account or internet access, and it stays available during normal operation (the device continues talking to the cloud in parallel — the local interface is additional, not a replacement). This document is a factual reference for the endpoints and fields the integration uses; every request/response shape below has been verified against a device on the LAN.

> **Safety:** `shutoff/SetShutoffValveState` actuates a physical valve on a live water main. Treat it as destructive — never call it without intent.

## Transport & auth

All calls are a single `POST` to `http://<host>/JNAP/`; the action is selected by a header, not the path.

```
POST http://<host>/JNAP/
Headers:
  X-JNAP-Authorization: Basic base64("admin:admin")   # static credentials
  X-JNAP-Action: <action URN>                          # see tables below
  Content-Type: application/json
Body: JSON
```

Responses are JSON envelopes: `{"result": "OK", "output": { ... }}`, or `{"result": "_Error...", "error": "..."}` on failure.

## Actions used by the integration

| Purpose | `X-JNAP-Action` | Body | Notes |
|---|---|---|---|
| Device identity | `http://phyn.com/jnap/core/GetDeviceInfo` | `{}` | `deviceID` (MAC), `serialNumber`, `deviceName`, `productCode`, `firmwareVersion` |
| Full telemetry | `http://phyn.com/jnap/attribute/get` | **`{}` (empty)** | returns everything as `{system, product, stats}` — the coordinator polls only this |
| Read valve state | `http://phyn.com/jnap/shutoff/GetShutoffValveState` | `{}` | `{"state": "Open"}`; also present as `product.sov_state_str` |
| **Set valve state** | `http://phyn.com/jnap/shutoff/SetShutoffValveState` | `{"state": "Open"\|"Close"}` | **moves a real valve** |

`attribute/get` returns the full attribute set **only with an empty body `{}`**; sending `{"attributes": [...]}` returns `_ErrorInvalidInput`.

## `attribute/get` fields of interest

| Field (group) | Meaning |
|---|---|
| `product.sensor_pressure_1` | water pressure (PSI) |
| `product.sensor_temperature_1` | water temperature (°F) |
| `product.sensor_flow` / `product.sensor_flow_state` | flow rate (GPM) / off·low·med·high |
| `product.sov_state_str` / `product.sov_close_count` | valve open/closed + actuation count |
| `product.consumption_total` | cumulative gallons |
| `product.alert_notifier_fp_state_str` | flow-alert / leak state (`normal` = OK) |
| `product.alert_notifier_fp_active_alerts` | count of active device alerts |
| `product.ml_oor_temperature_state` | freeze / out-of-range-temperature state |
| `product.ml_oor_pressure_state` / `product.ml_oor_flow_state` | out-of-range pressure / flow (`0` = normal, non-zero = out of range) |
| `product.sov_plumbing_check_in_progress` | leak test / plumbing check running |
| `product.ml_offline_leak_detector_enabled` | on-device auto-shutoff leak protection enabled |
| `stats.wifi_sta_rssi` | Wi-Fi signal (dBm) |
| `stats.net_connected` / `stats.wifi_connected` | connectivity |
| `stats.device_up_time_sec` | uptime (s) |

## Other actions (not used by the integration)

The firmware also advertises Wi-Fi/onboarding actions under the `setup/*` namespace. Most (e.g. `setup/GetWirelessNetworkConnectionStatus`) return `_ErrorUnknownAction` in normal operation and are only served during device onboarding. One exception verified live: `setup/GetWirelessNetworkList` **does** return a real-time Wi-Fi site survey during normal operation. Wi-Fi *re-provisioning* (`setup/ConnectToWirelessNetwork`) is deliberately untested — it is inherently disruptive (it would move the device to another network) and is assumed to require onboarding mode.

## Practical notes

- The device IP is DHCP-assigned and **changes**. Discover it by MAC OUI `28:F5:37:…` or by trying `GetDeviceInfo` across the LAN; a fixed DHCP reservation is recommended. The integration's DHCP discovery tracks lease changes automatically.
- Credentials are the static `admin:admin` Basic header; host is the only per-install input.
- `core`, `attribute`, and `shutoff` are the namespaces that matter for an integration; `setup/*` and `startup/*` are onboarding/diagnostic.
