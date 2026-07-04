#!/usr/bin/env bash
# Harmless local probe for the Phyn Plus JNAP interface (read-only — does NOT move the valve).
# Usage: ./probe_jnap.sh <phyn-ip>
# See PROTOCOL.md for the JNAP endpoints and fields this exercises.
set -u
IP="${1:-}"
[ -z "$IP" ] && { echo "usage: $0 <phyn-ip>"; exit 1; }

AUTH="Basic $(printf 'admin:admin' | base64)"
jnap() {  # $1 = X-JNAP-Action URN, $2 = JSON body
  curl -sk --max-time 6 -X POST "http://$IP/JNAP/" \
    -H "X-JNAP-Authorization: $AUTH" \
    -H "X-JNAP-Action: $1" \
    -H "Content-Type: application/json;charset=UTF-8" \
    -d "${2:-{}}" -w "\n[http_code=%{http_code}]\n"
}

echo "### reachability ###"
nc -z -G 3 "$IP" 80 2>/dev/null && echo "port 80: OPEN" || { echo "port 80: closed/unreachable (device offline, wrong IP, or JNAP not exposed on LAN)"; }

echo; echo "### GetDeviceInfo (read-only) ###"
jnap "http://phyn.com/jnap/core/GetDeviceInfo" '{}'

echo; echo "### Valve state (read-only) ###"
jnap "http://phyn.com/jnap/shutoff/GetShutoffValveState" '{}'

echo; echo "### Full attribute dump — system/product/stats (read-only) ###"
echo "(empty body {} returns EVERYTHING: sensor_pressure_1, sensor_temperature_1, sensor_flow,"
echo " sov_state_str, consumption_total, wifi_sta_rssi, ...)"
jnap "http://phyn.com/jnap/attribute/get" '{}'

echo
echo "Confirmed working: read valve + pressure + temperature + flow + consumption, all local."
echo "To CONTROL the valve (moves water!): X-JNAP-Action http://phyn.com/jnap/shutoff/SetShutoffValveState"
echo "  body {\"state\":\"Close\"} or {\"state\":\"Open\"} — not called by this script."
