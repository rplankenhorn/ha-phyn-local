# Phyn Local

A local-only (LAN, no cloud) Home Assistant integration for the Phyn Plus smart water shutoff valve — monitors pressure, temperature, flow, and consumption, and controls the shutoff valve over the local network. Unlike existing Phyn integrations, no cloud account or internet access needed.

## How it works

The Phyn Plus exposes a JNAP HTTP API on port 80 of your LAN (endpoints and fields documented in [PROTOCOL.md](PROTOCOL.md)). The integration polls the device every 30 seconds.

All monitoring and control is local. Loss of cloud or WAN connectivity does
not affect the integration while Home Assistant can still reach the powered
Phyn device over the LAN. The client also tolerates the malformed HTTP emitted
by affected PP2 firmware: it reads the declared JSON body and ignores the
firmware's leaked debug header and extra response data.

## Installation

### Via HACS (recommended)

1. Open **HACS** in Home Assistant
2. Go to **Integrations**
3. Click the **⋯** (three-dot menu) in the top right
4. Select **Custom repositories**
5. Add repository: `https://github.com/rplankenhorn/ha-phyn-local`
6. Select **Integration** as the category
7. Click **Create**
8. Find "Phyn Local" in HACS and click **Install**
9. Restart Home Assistant

### Manual installation

1. Download this repository
2. Copy the `custom_components/phyn_local` directory into your Home Assistant `config` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Phyn Local**
3. Enter your Phyn Plus device IP address

### Automatic discovery

The integration also auto-discovers the Phyn Plus via DHCP when the device (MAC prefix `28:F5:37`) renews its lease.

> **Note:** The device IP is DHCP-assigned and can change. It is recommended to set a DHCP reservation in your router. DHCP discovery will also track IP changes automatically.

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| Water valve | Valve | Open or close the water shutoff valve |
| Water pressure | Sensor | Current water pressure (PSI) |
| Water temperature | Sensor | Current water temperature (°F) |
| Water flow rate | Sensor | Current water flow rate (gal/min) |
| Total water consumption | Sensor | Total water consumption (gal) |
| Flow state | Sensor | Current flow state (off, low, medium, high) |
| Wi-Fi signal | Sensor | Wi-Fi signal strength (diagnostic) |
| Valve close count | Sensor | Number of times the valve has been closed (diagnostic) |
| Uptime | Sensor | Device uptime in seconds (diagnostic) |
| Active alerts | Sensor | Count of active device alerts (diagnostic) |
| Leak detected | Binary sensor | Indicates if a leak has been detected (diagnostic) |
| Freeze risk | Binary sensor | Indicates if freeze protection is triggered (diagnostic) |
| Pressure out of range | Binary sensor | Water pressure outside the normal range (diagnostic) |
| Abnormal flow | Binary sensor | Water flow flagged as out of range (diagnostic) |
| Leak test running | Binary sensor | Plumbing check / auto leak test in progress (diagnostic) |
| Offline leak protection | Binary sensor | On-device auto-shutoff leak protection is enabled (diagnostic) |
| Online | Binary sensor | Indicates if the device is online (diagnostic) |

The valve reports `open` or `closed` only when the device's controller states
agree on a final position. During travel it can report `opening` or `closing`;
partial positions, disagreements, and unknown firmware values are reported as
`unknown` rather than being mistaken for closed.

After an explicit Open command, the integration verifies the position for up
to 15 seconds. If the valve remains non-final, it sends exactly one additional
Open command and verifies for another 15 seconds. It never retries from passive
polling, after a confirmed closed state, or while an active leak is reported.
A persistent partial-open failure raises a service error and a Home Assistant
Repairs issue; the issue clears after a later poll confirms the valve is fully
open.

## Safety warning

The water valve entity operates a **real water shutoff valve on your main water line**. Use responsibly and test in a controlled manner.

## Compatibility

- **Device:** Phyn Plus (PP2) on firmware 4.9.x and compatible versions
- **Home Assistant:** 2024.4 and later

## Contributing

Contributions are welcome, and **AI-assisted contributions are encouraged** — this project was built with AI coding agents and is set up for them. Before starting, read [AGENTS.md](AGENTS.md): work is tracked with [beads](https://github.com/gastownhall/beads) (`bd ready` to find a task, `bd update <id> --claim`, `bd close <id>`), and there's a model/delegation policy to keep contributions cost-effective. Human PRs are equally welcome — just follow the same task-tracking workflow.

## Credits and disclaimer

- Local JNAP protocol reference: [PROTOCOL.md](PROTOCOL.md)
- Not affiliated with or endorsed by Phyn LLC
- Use at your own risk
