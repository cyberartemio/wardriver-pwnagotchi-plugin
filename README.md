# 🛜 Wardriver Pwnagotchi plugin

![GitHub Release](https://img.shields.io/github/v/release/cyberartemio/wardriver-pwnagotchi-plugin?style=flat-square)
 ![GitHub issues](https://img.shields.io/github/issues/cyberartemio/wardriver-pwnagotchi-plugin?style=flat-square)
 ![GitHub License](https://img.shields.io/github/license/cyberartemio/wardriver-pwnagotchi-plugin?style=flat-square)

A simple plugin for wardriving on your pwnagotchi. It saves all networks seen by bettercap on files using CSV format compatible with WiGLE (not only the ones whose handshakes has been collected). Optionally, it can also automatically uploads sessions file on WiGLE.

## 🚀 Installation

> [!IMPORTANT]
> This plugin requires a GPS module attached to your pwnagotchi. You also need to activate and configure the `gps` plugin (or another plugin that configures bettercap gps function).
>
> If you want to enable WiGLE upload, you need a valid API key.

1. Login inside your pwnagotchi using SSH:
```sh
ssh pi@10.0.0.2
```
2. Go to `custom_plugins` directory where all custom plugins of your Pwnagotchi are stored:
```sh
cd /path/to/custom_plugins/directory
```
3. Download the plugin code:
```sh
wget https://raw.githubusercontent.com/cyberartemio/wardriver-pwnagotchi-plugin/main/wardriver.py
```
5. Edit your configuration file (`/etc/pwnagotchi/config.toml`) and add the following:
```toml
# Enable the plugin
main.plugins.wardriver.enabled = true
# Directory where CSV files will be stored
main.plugins.wardriver.csv_path = "/root/wardriver"
# Enable WiGLE file uploading
main.plugins.wardriver.wigle.enabled = true
# WiGLE API key (encoded)
main.plugins.wardriver.wigle.api_key = "xyz..."
# Enable commercial use of your reported data
main.plugins.wardriver.wigle.donate = false
# OPTIONAL: networks whitelist aka don't log these networks
main.plugins.wardriver.whitelist = [
    "network-1",
    "network-2"
]
# NOTE: SSIDs in main.whitelist will always be ignored
```
6. Restart daemon service:
```sh
sudo systemctl restart pwnagotchi
```

Done! Now the plugin is installed and is working.

## ✨ Usage

*Once configured, the plugin works autonomously and you don't have to do anything. Check the sections below to learn more about how it works.*

### 🚗 Wardriving

Everytime bettercap refresh the access points list (normally every 2 minutes more or less), the plugin will log the new networks seen along with the latitude, longitude and altitude. Everytime the service is restarted a new session file will be created.

The CSV file format used is compatible with WiGLE and in the pre-header of the file are logged the informations about your device.

If you don't want some networks to be logged, you can add the SSID inside `whitelist` array in the config. Wardriver does not report networks whose SSID is contained within the whitelist.

**Note:** the SSIDs inside the `main.whitelist` array will always be ignored.

### 🌐 WiGLE automatic upload

If you have enabled it, once internet is available, the plugin will upload all previous session files on WiGLE. Once a file has been reported it will be marked as uploaded so it will not be sent another time to WiGLE. For marking the file, the plugin appends `_uploaded` to the corresponding file. If a file fails to upload, wardriver will retry to upload it on next sessions reporting (tipically checks and report every 5 minutes).

Please note that the current session file will not be uploaded as it is considered still in progress. Don't worry, it'll be uploaded the next time your pwnagotchi starts a new wardriving session.

## ❤️ Contribution

If you need help or you want to suggest new ideas, you can open an issue [here](https://github.com/cyberartemio/wardriver-pwnagotchi-plugin/issues/new).

If you want to contribute, you can fork the project and then open a pull request.
