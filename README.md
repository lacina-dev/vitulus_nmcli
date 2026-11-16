# vitulus_nmcli
 ROS package for Network Manager.

## Node `network_manager` (namespace `nmcli`)

Topics (all latched):

| topic | when | readers |
|---|---|---|
| `conn_detail` (`NmConnDetail`) | every 1 s, from the last reading (fresh stamp) | `device_state_publisher` (wifi icon; stale after 3 s), `nextion_lcd` |
| `conn_list` (`NmConn`) | on change + every `~refresh_period` | `nextion_lcd` |
| `ssid_list` (`NmSsidList`) | after each AP scan (180 s, or `scan_ap`) + every `~refresh_period` | `nextion_lcd` |

Reading NetworkManager over D-Bus (T39, 2026-11-16): every second only a cheap look
(active connections, their state and IPv4 config object). The full read (saved
connections, settings of the active wifi, addresses/routes/DNS) runs when that look
changes, after an own action (`conn_activate`, `conn_add`, `conn_del`,
`disconnect_wifi`, `scan_ap`) and at least every `~refresh_period` seconds (default 15).
A connection coming up/going down or a new DHCP lease is visible within ~1 s; a saved
connection added outside the node (e.g. `nmcli`) within `~refresh_period`.

The wifi password is never read (no `GetSecrets`) and never published: `conn_detail.psk`
stays empty.

Offline test (no ROS, no D-Bus): `python3 test/test_network_manager.py`.
