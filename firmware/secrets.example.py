# Template for the passwords file. Copy it to secrets.py (which stays out of git) and fill it in.
UPDATE_PASSWORD = ""  # password for updates over Wi-Fi (tools/enviar.py); empty = disabled

# The Wi-Fi network is set up through the Pico's own network and kept in wifi.json (docs/wifi.md). These two lines only
# apply while there is no wifi.json (Picos installed before that); they may stay empty.
WIFI_SSID = ""
WIFI_PASSWORD = ""
