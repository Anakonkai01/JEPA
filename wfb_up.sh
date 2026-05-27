#!/bin/bash
# wfb_up.sh — bring up WFB-NG ground station
# Cắm USB WiFi → bật RunCam → ./wfb_up.sh
# Ctrl+C để dừng

set -e

# Find RTL8812AU interface by USB ID (0bda:8812)
IFACE=$(for dev in /sys/class/net/*/; do
    iface=$(basename "$dev")
    if readlink -f "$dev/device" 2>/dev/null | grep -q "0bda:8812\|0BDA:8812"; then
        echo "$iface"; break
    fi
done)

if [ -z "$IFACE" ]; then
    IFACE="wlan1"
    echo "[warn] RTL8812AU not found by USB ID, falling back to $IFACE"
fi

echo "[1/2] Setting $IFACE to monitor mode on ch161..."
sudo nmcli dev set "$IFACE" managed no 2>/dev/null || true
sudo ip link set "$IFACE" down
sudo iw "$IFACE" set monitor otherbss
sudo ip link set "$IFACE" up
sudo iw "$IFACE" set channel 161 HT20
echo "      $(iw "$IFACE" info | grep -E 'type|channel' | tr -d '\t')"

echo "[2/2] Starting wfb_rx (Ctrl+C to stop)..."
sudo /home/anakonkai/wfb-ng/wfb_rx \
    -p 0 -u 5600 -K /home/anakonkai/gs.key -i 7669206 "$IFACE"
