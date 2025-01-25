# 🛜 Wardriver Pwnagotchi plugin

[![Discord server](https://img.shields.io/badge/Discord%20server-7289da?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/5vrJbbW3ve)
 ![GitHub Release](https://img.shields.io/github/v/release/cyberartemio/wardriver-pwnagotchi-plugin?style=flat-square)
 ![GitHub issues](https://img.shields.io/github/issues/cyberartemio/wardriver-pwnagotchi-plugin?style=flat-square)
 ![GitHub License](https://img.shields.io/github/license/cyberartemio/wardriver-pwnagotchi-plugin?style=flat-square)

A simple plugin for wardriving on your pwnagotchi. It saves all networks seen by bettercap, not only the ones whose handshakes has been collected. In this version all the operations are done through the plugin's webui. Inside of it, you can see the current wardriving session stats, global stats (including your WiGLE profile), all networks seen by your pwnagotchi and also plot the networks on map.

You can still upload automatically the sessions to WiGLE, but you can also uploads them manually using the webui.

<div align="center">
    <h3>Join our crew and start sailing with us! 🏴‍☠️</h3>
    <img src=".github/assets/banner.png" alt="" />
    <p>Open <a href="https://wigle.net/stats#groupstats">https://wigle.net/stats#groupstats</a>, search for "<b>The crew of the Black Pearl</b>" and click "<code>join</code>"</p>
</div>

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
wget https://github.com/cyberartemio/wardriver-pwnagotchi-plugin/archive/main.zip
```
4. Extract files and remove useless files:
```sh
unzip main.zip &&
mv wardriver-pwnagotchi-plugin-main/wardriver.py . &&
mv wardriver-pwnagotchi-plugin-main/wardriver_assets .&&
rm -r wardriver-pwnagotchi-plugin-main main.zip
```
5. Edit your configuration file (`/etc/pwnagotchi/config.toml`) and add the following:
```toml
# Enable the plugin
main.plugins.wardriver.enabled = true

# Path where SQLite db will be saved
main.plugins.wardriver.path = "/root/wardriver"

# Enable UI status text
main.plugins.wardriver.ui.enabled = true
# Enable UI icon
main.plugins.wardriver.ui.icon = true
# Set to true if black background, false if white background
main.plugins.wardriver.ui.icon_reverse = false

# Position of UI status text
main.plugins.wardriver.ui.position.x = 7
main.plugins.wardriver.ui.position.y = 95

# Enable WiGLE automatic file uploading
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

# GPS configuration
main.plugins.wardriver.gps.method = "bettercap" # or "gpsd" for gpsd or "pwndroid" for Pwndroid app
```
6. Restart daemon service:
```sh
sudo systemctl restart pwnagotchi
```

Done! Now the plugin is installed and is working.

### 📍 GPS Configuration

Starting from version v2.3, Wardriver supports different methods to retrieve the GPS position. Currently it supports:
- **Bettercap**: getting the position directly from Bettercap's agent
- **GPSD**: getting the position from GPSD daemon
- **Pwndroid**: getting the position from pwndroid Android companion application

Check one of the below section to understand how to configure each method for GPS position.

#### 🥷 Bettercap

If you are using the default gps plugin that add the GPS data to Bettercap, pick and use this method. **This is the default and the fallback choice, if you don't specify something else in the `config.toml`.**

```toml
# ...
main.plugins.wardriver.gps.method = "bettercap"
# ...
```

#### 🛰️ GPSD

If you are using Rai's gpsdeasy plugin, pick and use this method. This should be used if you have installed gpsd on your pwnagotchi and if it is running as a daemon.

```toml
# ...
main.plugins.wardriver.gps.method = "gpsd"

# OPTIONAL: if the gpsd daemon is running on another host, specify here the IP address.
# By default, localhost is used
main.plugins.wardriver.gps.host = "127.0.0.1"

# OPTIONAL: if the gpsd daemon is running on another host, specify here the port number.
# By default, 2947 is used
main.plugins.wardriver.gps.port = 2947
# ...
```

#### 📱 Pwndroid

> [!IMPORTANT]
> Be sure to have `websockets` pip library installed. Run `sudo apt install python3-websockets` on your pwnagotchi.

If you don't have a GPS device connected to your pwnagotchi, but you want to get the position from your Android phone, then pick this method. You should have installed the Jayofelony's Pwndroid companion application.

```toml
# ...
main.plugins.wardriver.gps.method = "pwndroid"

# OPTIONAL: add the IP address of your phone. This should be changed ONLY if you have changed the BT network addresses.
main.plugins.wardriver.gps.host = "192.168.44.1"

# OPTIONAL: add the port number where the Pwndroid websocket is listening on. This shouldn't be changed, unless the
# application is updated with a different configuration. By default, 8080 is used
main.plugins.wardriver.gps.port = 8080
# ...
```

## ✨ Usage

*Once configured, the plugin works autonomously and you don't have to do anything. Check the sections below to learn more about how it works.*

### 🚗 Wardriving

Everytime bettercap refresh the access points list (normally every 2 minutes more or less), the plugin will log the new networks seen along with the latitude, longitude and altitude. Each time the service is restarted a new session will be created. If you have enabled it, the plugin will display the total number of networks of the current session on the pwnagotchi display.

If you don't want some networks to be logged, you can add the SSID inside `wardriver.whitelist` array in the config. Wardriver does not report networks whose SSID is contained within the local and global whitelist.

**Note:** the SSIDs inside the `main.whitelist` array will always be ignored.

### 🌐 WiGLE automatic upload

If you have enabled it, once internet is available, the plugin will upload all previous session files on WiGLE. Please note that the current session will not be uploaded as it is considered still in progress. Don't worry, it'll be uploaded the next time your pwnagotchi starts with internet connection.

If you just want to upload sessions to WiGLE manually you can still do it. All you have to do, is configuring your api key and use the corresponding button in the sessions tab of the web ui. You can also download the CSV file locally for a specific session.

## ❤️ Contribution

If you need help or you want to suggest new ideas, you can open an issue [here](https://github.com/cyberartemio/wardriver-pwnagotchi-plugin/issues/new) or you can join my Discord server using this [invite](https://discord.gg/5vrJbbW3ve).

If you want to contribute, you can fork the project and then open a pull request.
