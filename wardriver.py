import logging
import re
import sqlite3
import os
from datetime import datetime, timezone
import toml
from threading import Lock
import json
import requests
from PIL import Image, ImageOps
import pwnagotchi.plugins as plugins
from pwnagotchi.ui.components import LabeledValue, Widget
from pwnagotchi.ui.view import BLACK
import pwnagotchi.ui.fonts as fonts
from flask import abort
from flask import render_template_string

class Database():
    def __init__(self, path):
        self.__path = path
        self.__db_connect()
        self.remove_empty_sessions() # Remove old sessions that don't have networks
    
    def __db_connect(self):
        logging.info('[WARDRIVER] Setting up database connection...')
        self.__connection = sqlite3.connect(self.__path, check_same_thread = False, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        self.__cursor = self.__connection.cursor()
        self.__cursor.execute('CREATE TABLE IF NOT EXISTS sessions ("id" INTEGER, "created_at" TEXT DEFAULT CURRENT_TIMESTAMP, "wigle_uploaded" INTEGER DEFAULT 0, PRIMARY KEY("id" AUTOINCREMENT))') # sessions table contains wardriving sessions
        self.__cursor.execute('CREATE TABLE IF NOT EXISTS networks ("id" INTEGER, "mac" TEXT NOT NULL, "ssid" TEXT, PRIMARY KEY ("id" AUTOINCREMENT))') # networks table contains seen networks without coordinates/sessions info
        self.__cursor.execute('CREATE TABLE IF NOT EXISTS wardrive ("id" INTEGER, "session_id" INTEGER NOT NULL, "network_id" INTEGER NOT NULL, "auth_mode" TEXT NOT NULL, "latitude" TEXT NOT NULL, "longitude" TEXT NOT NULL, "altitude" TEXT NOT NULL, "accuracy" INTEGER NOT NULL, "channel" INTEGER NOT NULL, "rssi" INTEGER NOT NULL, "seen_timestamp" TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY("id" AUTOINCREMENT), FOREIGN KEY("session_id") REFERENCES sessions("id"), FOREIGN KEY("network_id") REFERENCES networks("id"))') # wardrive table contains the relations between sessions and networks with timestamp and coordinates
        self.__connection.commit()
        logging.info('[WARDRIVER] Succesfully connected to db')
    
    def disconnect(self):
        self.__cursor.close()
        self.__connection.commit()
        self.__connection.close()
        logging.info('[WARDRIVER] Closed db connection')

    def new_wardriving_session(self, timestamp = None, wigle_uploaded = False):
        if timestamp:
            self.__cursor.execute('INSERT INTO sessions(created_at, wigle_uploaded) VALUES (?, ?)', [timestamp, wigle_uploaded])
        else:
            self.__cursor.execute('INSERT INTO sessions(wigle_uploaded) VALUES (?)', [wigle_uploaded]) # using default values
        session_id = self.__cursor.lastrowid
        self.__connection.commit()
        return session_id
    
    def add_wardrived_network(self, session_id, mac, ssid, auth_mode, latitude, longitude, altitude, accuracy, channel, rssi, seen_timestamp = None):
        self.__cursor.execute('SELECT id FROM networks WHERE mac = ? AND ssid = ?', [mac, ssid])
        network = self.__cursor.fetchone()
        network_id = network[0] if network else None
        if(not network_id):
            self.__cursor.execute('INSERT INTO networks(mac, ssid) VALUES (?, ?)', [mac, ssid])
            network_id = self.__cursor.lastrowid
        
        if seen_timestamp:
            self.__cursor.execute('INSERT INTO wardrive(session_id, network_id, auth_mode, latitude, longitude, altitude, accuracy, channel, rssi, seen_timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [session_id, network_id, auth_mode, latitude, longitude, altitude, accuracy, channel, rssi, seen_timestamp])
        else:
            self.__cursor.execute('INSERT INTO wardrive(session_id, network_id, auth_mode, latitude, longitude, altitude, accuracy, channel, rssi) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [session_id, network_id, auth_mode, latitude, longitude, altitude, accuracy, channel, rssi])
        self.__connection.commit()
   
    def session_networks_count(self, session_id):
        '''
        Return the total networks count for a wardriving session given its id
        '''
        self.__cursor.execute('SELECT COUNT(wardrive.id) FROM wardrive JOIN networks ON wardrive.network_id = networks.id WHERE wardrive.session_id = ? GROUP BY wardrive.session_id', [session_id])
        row = self.__cursor.fetchone()
        return row[0] if row else 0

    def session_networks(self, session_id):
        '''
        Return networks data for a wardriving session given its id
        '''
        networks = []
        self.__cursor.execute('SELECT networks.mac, networks.ssid, wardrive.auth_mode, wardrive.latitude, wardrive.longitude, wardrive.altitude, wardrive.accuracy, wardrive.channel, wardrive.rssi, wardrive.seen_timestamp FROM wardrive JOIN networks ON wardrive.network_id = networks.id WHERE wardrive.session_id = ?', [session_id])
        rows = self.__cursor.fetchall()
        for row in rows:
            mac, ssid, auth_mode, latitude, longitude, altitude, accuracy, channel, rssi, seen_timestamp = row
            networks.append({
                'mac': mac,
                'ssid': ssid,
                'auth_mode': auth_mode,
                'latitude': latitude,
                'longitude': longitude,
                'altitude': altitude,
                'accuracy': accuracy,
                'channel': channel,
                'rssi': rssi,
                'seen_timestamp': seen_timestamp
            })

        return networks

    def session_uploaded_to_wigle(self, session_id):
        self.__cursor.execute('UPDATE sessions SET "wigle_uploaded" = 1 WHERE id = ?', [session_id])
        self.__connection.commit()
    
    def wigle_sessions_not_uploaded(self, current_session_id):
        '''
        Return the list of ids of sessions that haven't got uploaded on WiGLE excluding `current_session_id`
        '''
        sessions_ids = []
        self.__cursor.execute('SELECT id FROM sessions WHERE wigle_uploaded = 0 AND id <> ?', [current_session_id])
        rows = self.__cursor.fetchall()
        for row in rows:
            sessions_ids.append(row[0])
        return sessions_ids

    def remove_empty_sessions(self):
        '''
        Remove all sessions that doesn't have any network
        '''
        self.__cursor.execute('DELETE FROM sessions WHERE sessions.id NOT IN (SELECT wardrive.session_id FROM wardrive GROUP BY wardrive.session_id)')
        self.__connection.commit()
    
    # Web UI queries
    def general_stats(self):
        self.__cursor.execute('SELECT COUNT(id) FROM networks')
        total_networks = self.__cursor.fetchone()[0]
        self.__cursor.execute('SELECT COUNT(id) FROM sessions')
        total_sessions = self.__cursor.fetchone()[0]
        self.__cursor.execute('SELECT COUNT(id) FROM sessions WHERE wigle_uploaded = 1')
        sessions_uploaded = self.__cursor.fetchone()[0]
        return {
            'total_networks': total_networks,
            'total_sessions': total_sessions,
            'sessions_uploaded': sessions_uploaded
        }
    
    def sessions(self):
        self.__cursor.execute('SELECT sessions.*, COUNT(wardrive.id) FROM sessions JOIN wardrive ON sessions.id = wardrive.session_id GROUP BY sessions.id')
        rows = self.__cursor.fetchall()
        sessions = []
        for row in rows:
            sessions.append({
                'id': row[0],
                'created_at': row[1],
                'wigle_uploaded': row[2] == 1,
                'networks': row[3]
            })
        return sessions
    
    def current_session_stats(self, session_id):
        self.__cursor.execute('SELECT created_at FROM sessions WHERE id = ?', [session_id])
        created_at = self.__cursor.fetchone()[0]
        self.__cursor.execute('SELECT COUNT(id) FROM wardrive WHERE session_id = ?', [session_id])
        networks = self.__cursor.fetchone()[0]
        return {
            "id": session_id,
            "created_at": created_at,
            "networks": networks
        }

    def networks(self):
        cursor = self.__connection.cursor()
        cursor.execute('SELECT n.*, MIN(w.seen_timestamp), MIN(w.session_id), MAX(w.seen_timestamp), MAX(w.session_id), COUNT(n.id) FROM networks n JOIN wardrive w ON n.id = w.network_id GROUP BY n.id')
        rows = cursor.fetchall()
        networks = []
        for row in rows:
            id, mac, ssid, first_seen, first_session, last_seen, last_session, sessions_count = row
            networks.append({
                "id": id,
                "mac": mac,
                "ssid": ssid,
                "first_seen": first_seen,
                "first_session": first_session,
                "last_seen": last_seen,
                "last_session": last_session,
                "sessions_count": sessions_count
            })
        cursor.close()
        
        return networks

    def map_networks(self):
        cursor = self.__connection.cursor()
        cursor.execute('SELECT n.mac, n.ssid, w.latitude, w.longitude, w.altitude, w.accuracy FROM networks n JOIN wardrive w ON n.id = w.network_id')
        rows = cursor.fetchall()
        networks = []
        for row in rows:
            mac, ssid, latitude, longitude, altitude, accuracy = row
            networks.append({
                "mac": mac,
                "ssid": ssid,
                "latitude": float(latitude),
                "longitude": float(longitude),
                "altitude": float(altitude),
                "accuracy": int(accuracy)
            })
        cursor.close()
        
        return networks

class CSVGenerator():
    def __init__(self):
       self.__wigle_info()
        
    def __wigle_info(self):
        '''
        Return info used in CSV pre-header
        '''
        try:
            with open('/etc/pwnagotchi/config.toml', 'r') as config_file:
                data = toml.load(config_file)
                # Pwnagotchi name
                device = data['main']['name']
                # Pwnagotchi display model
                display = data['ui']['display']['type'] # Pwnagotchi display
        except Exception:
            device = 'pwnagotchi'
            display = 'unknown'

        # Preheader formatting
        file_format = 'WigleWifi-1.4'
        app_release = Wardriver.__version__
        # Device model
        try:
            with open('/sys/firmware/devicetree/base/model', 'r') as model_info:
                model = model_info.read()
        except Exception:
            model = 'unknown'
        # OS version
        try:
            with open('/etc/os-release', 'r') as release_info:
                release = release_info.read().split('\n')[0].split('=')[-1].replace('"', '')
        except Exception:
            release = 'unknown'
        # CPU model
        try:
            with open('/proc/cpuinfo', 'r') as cpu_model:
                board = cpu_model.read().split('\n')[1].split(':')[1][1:]
        except Exception:
            board = 'unknown'
        
        # Brand: currently set equal to model
        brand = model

        self.__wigle_file_format = file_format
        self.__wigle_app_release = app_release
        self.__wigle_model = model
        self.__wigle_release = release
        self.__wigle_device = device
        self.__wigle_display = display
        self.__wigle_board = board
        self.__wigle_brand = brand

    def __csv_header(self):
        return 'MAC,SSID,AuthMode,FirstSeen,Channel,RSSI,CurrentLatitude,CurrentLongitude,AltitudeMeters,AccuracyMeters,Type\n'
    
    def __csv_network(self, network):
        return f'{network["mac"]},{network["ssid"]},{network["auth_mode"]},{network["seen_timestamp"]},{network["channel"]},{network["rssi"]},{network["latitude"]},{network["longitude"]},{network["altitude"]},{network["accuracy"]},WIFI\n'

    def networks_to_csv(self, networks):
        csv = self.__csv_header()
        for network in networks:
            csv += self.__csv_network(network)
        return csv

    def networks_to_wigle_csv(self, networks):
        pre_header = f'{self.__wigle_file_format},{self.__wigle_app_release},{self.__wigle_model},{self.__wigle_release},{self.__wigle_device},{self.__wigle_display},{self.__wigle_board},{self.__wigle_brand}\n'
        
        return pre_header + self.networks_to_csv(networks)

class Wardriver(plugins.Plugin):
    __author__ = 'CyberArtemio'
    __version__ = '2.2'
    __license__ = 'GPL3'
    __description__ = 'A wardriving plugin for pwnagotchi. Saves all networks seen and uploads data to WiGLE once internet is available'

    DEFAULT_PATH = '/root/wardriver' # SQLite database default path
    DATABASE_NAME = 'wardriver.db' # SQLite database file name

    def __init__(self):
        logging.debug('[WARDRIVER] Plugin created')
    
    def on_loaded(self):
        logging.info('[WARDRIVER] Plugin loaded (join the Discord server: https://discord.gg/5vrJbbW3ve)')

        self.__lock = Lock()
        self.ready = False
        self.__gps_available = True

        try:
            self.__path = self.options['path']
        except Exception:
            self.__path = self.DEFAULT_PATH
        
        try:
            self.__ui_enabled = self.options['ui']['enabled']
        except Exception:
            self.__ui_enabled = False
        
        self.__assets_path = os.path.join(os.path.dirname(__file__), "wardriver_assets")
        if not os.path.isfile(os.path.join(self.__assets_path, 'icon_error.bmp')):
            logging.critical('[WARDRIVER] Missing wardriver/icon_error.bmp, download it from GitHub repo')
        if not os.path.isfile(os.path.join(self.__assets_path, 'icon_working.bmp')):
            logging.critical('[WARDRIVER] Missing wardriver/icon_working.bmp, download it from GitHub repo')
        
        try:
            self.__icon = self.options['ui']['icon']
        except Exception:
            self.__icon = True
        
        try:
            self.__reverse = self.options['ui']['icon_reverse']
        except Exception:
            self.__reverse = False

        try:
            self.__ui_position = (self.options['ui']['position']['x'], self.options['ui']['position']['y'])
        except Exception:
            self.__ui_position = (7, 95)
        
        try:
            self.__whitelist = self.options['whitelist']
        except Exception:
            self.__whitelist = []

        self.__load_global_whitelist()        
        
        try:
            self.__wigle_api_key = self.options['wigle']['api_key']
        except Exception:
            self.__wigle_api_key = None
        try:
            self.__wigle_donate = self.options['wigle']['donate']
        except Exception:
            self.__wigle_donate = False
        try:
            self.__wigle_enabled = self.options['wigle']['enabled']
            
            if self.__wigle_enabled and (not self.__wigle_api_key or self.__wigle_api_key == ''):
                logging.error('[WARDRIVER] Wigle enabled but no api key provided!')
                self.__wigle_enabled = False
        except Exception:
            self.__wigle_enabled = False
        
        if not os.path.exists(self.__path):
            os.makedirs(self.__path)
            logging.warning('[WARDRIVER] Created db directory')
        
        self.__db = Database(os.path.join(self.__path, self.DATABASE_NAME))
        self.__csv_generator = CSVGenerator()
        self.__session_reported = [] # TODO: remove
        self.__last_ap_refresh = None
        self.__last_ap_reported = []

        logging.info(f'[WARDRIVER] Wardriver DB can be found in {self.__path}')
        
        if self.__wigle_enabled:
            logging.info('[WARDRIVER] Previous sessions will be uploaded to WiGLE once internet is available')
            logging.info('[WARDRIVER] Join the WiGLE group: search "The crew of the Black Pearl" and start wardriving with us!')

        self.__session_id = -1

        self.__import_old_csv()
    
    def on_ready(self, agent):
        if not agent.mode == 'MANU':
            self.__session_id = self.__db.new_wardriving_session()
            self.ready = True

            if len(self.__whitelist) > 0:
                logging.info(f'[WARDRIVER] Ignoring {len(self.__whitelist)} networks')
        
    def __load_global_whitelist(self):
        try:
            with open('/etc/pwnagotchi/config.toml', 'r') as config_file:
                data = toml.load(config_file)
                for ssid in data['main']['whitelist']:
                    if ssid not in self.__whitelist:
                        self.__whitelist.append(ssid)
        except Exception as e:
            logging.critical('[WARDRIVER] Cannot read global config. Networks in global whitelist will NOT be ignored')
    
    def __import_old_csv(self):
        '''
        Import previous version csv files (<timestamp>.csv and wardriver_db.csv)
        '''
        # Import wardriver_db.csv
        csv_db = os.path.join(self.__path, 'wardriver_db.csv')
        if os.path.exists(csv_db):
            logging.info(f'[WARDRIVER] Importing old {csv_db} into the db')
            try:
                with open(csv_db, 'r') as file:
                    data = file.readlines()[1:]
                    session_id = self.__db.new_wardriving_session(wigle_uploaded = True)
                    for row in data:
                        row = row.replace('\n', '')
                        mac, ssid, auth_mode, seen_timestamp, channel, rssi, latitude, longitude, altitude, accuracy, entry_type = row.split(',')
                        self.__db.add_wardrived_network(session_id = session_id,
                                                        mac = mac,
                                                        ssid = ssid,
                                                        auth_mode = auth_mode,
                                                        latitude = latitude,
                                                        longitude = longitude,
                                                        altitude = altitude,
                                                        accuracy = accuracy,
                                                        channel = channel,
                                                        rssi = rssi,
                                                        seen_timestamp = seen_timestamp)
                os.remove(csv_db)
                logging.info(f'[WARDRIVER] Successfully imported {csv_db}')
            except Exception as e:
                logging.error(f'[WARDRIVER] Error while importing {csv_db} file: {e}')
        # Import all <timestamp>.csv
        pattern = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.csv')
        sessions_files = [ file for file in os.listdir(self.__path) if pattern.match(file) ]
        for session in sessions_files:
            try:
                session_path = os.path.join(self.__path, session)
                logging.info(f'[WARDRIVER] Importing {session_path} into the db')
                with open(session_path, 'r') as file:
                    data = file.readlines()[2:]
                    session_date = datetime.strptime(session.replace('.csv', ''), '%Y-%m-%dT%H:%M:%S')
                    session_id = self.__db.new_wardriving_session(wigle_uploaded = True, timestamp = session_date)
                    for row in data:
                        row = row.replace('\n', '')
                        mac, ssid, auth_mode, seen_timestamp, channel, rssi, latitude, longitude, altitude, accuracy, entry_type = row.split(',')
                        self.__db.add_wardrived_network(session_id = session_id,
                                                        mac = mac,
                                                        ssid = ssid,
                                                        auth_mode = auth_mode,
                                                        latitude = latitude,
                                                        longitude = longitude,
                                                        altitude = altitude,
                                                        accuracy = accuracy,
                                                        channel = channel,
                                                        rssi = rssi,
                                                        seen_timestamp = seen_timestamp)
                os.remove(session_path)
                logging.info(f'[WARDRIVER] Successfully imported {session_path}')
            except Exception as e:
                logging.error(f'[WARDRIVER] Error while importing {session_path} file: {e}')
    
    def on_ui_setup(self, ui):
        if self.__ui_enabled:
            logging.info('[WARDRIVER] Adding status text to ui')
            wardriver_text_pos = (self.__ui_position[0] + 13, self.__ui_position[1]) if self.__icon else self.__ui_position
            wardriver_text_label = '' if self.__icon else 'wardrive:'
            ui.add_element('wardriver', LabeledValue(color = BLACK,
                                            label = wardriver_text_label,
                                            value = "Not started",
                                            position = wardriver_text_pos,
                                            label_font = fonts.Small,
                                            text_font = fonts.Small))
            
            if self.__icon:
                ui.add_element('wardriver_icon', WardriverIcon(path = f'{self.__assets_path}/icon_working.bmp', xy = self.__ui_position, reverse = self.__reverse))
                self.__current_icon = 'icon_working'

    def on_ui_update(self, ui):
        if self.__ui_enabled and self.ready:
            ui.set('wardriver', f'{self.__db.session_networks_count(self.__session_id)} {"networks" if self.__icon else "nets"}')
            if self.__gps_available and self.__current_icon == 'icon_error':
                ui.remove_element('wardriver_icon')
                ui.add_element('wardriver_icon', WardriverIcon(path = f'{self.__assets_path}/icon_working.bmp', xy = self.__ui_position, reverse = self.__reverse))
                self.__current_icon = 'icon_working'
            elif not self.__gps_available and self.__current_icon == 'icon_working':
                ui.remove_element('wardriver_icon')
                ui.add_element('wardriver_icon', WardriverIcon(path = f'{self.__assets_path}/icon_error.bmp', xy = self.__ui_position, reverse = self.__reverse))
                self.__current_icon = 'icon_error'

    def on_unload(self, ui):
        if self.__ui_enabled:
            with ui._lock:
                ui.remove_element('wardriver')
                if self.__icon:
                    ui.remove_element('wardriver_icon')
        self.__db.disconnect()
        logging.info('[WARDRIVER] Plugin unloaded')

    def __filter_whitelist_aps(self, unfiltered_aps):
        '''
        Filter whitelisted networks
        '''
        filtered_aps = [ ap for ap in unfiltered_aps if ap['hostname'] not in self.__whitelist ]
        return filtered_aps
    
    def __filter_reported_aps(self, unfiltered_aps):
        '''
        Filter already reported networks
        '''
        filtered_aps = [ ap for ap in unfiltered_aps if (ap['mac'], ap['hostname']) not in self.__session_reported ]
        return filtered_aps

    def on_unfiltered_ap_list(self, agent, aps):
        info = agent.session()
        gps_data = info["gps"]

        if not self.ready: # it is ready once the session file has been initialized with pre-header and header
            logging.error('[WARDRIVER] Plugin not ready... skip wardriving log')

        if gps_data and all([
            # avoid 0.000... measurements
            gps_data["Latitude"], gps_data["Longitude"]
        ]):
            self.__gps_available = True
            self.__last_ap_refresh = datetime.now()
            self.__last_ap_reported = []
            coordinates = {
                'latitude': gps_data["Latitude"],
                'longitude': gps_data["Longitude"],
                'altitude': gps_data["Altitude"],
                'accuracy': 50 # TODO: how can this be calculated?
            }

            filtered_aps = self.__filter_whitelist_aps(aps)
            filtered_aps = self.__filter_reported_aps(filtered_aps)
            
            if len(filtered_aps) > 0:
                logging.info(f'[WARDRIVER] Discovered {len(filtered_aps)} new networks')
                for ap in filtered_aps:
                    mac = ap['mac']
                    ssid = ap['hostname'] if ap['hostname'] != '<hidden>' else ''
                    capabilities = ''
                    if ap['encryption'] != '':
                        capabilities = f'{capabilities}[{ap["encryption"]}]'
                    if ap['cipher'] != '':
                        capabilities = f'{capabilities}[{ap["cipher"]}]'
                    if ap['authentication'] != '':
                        capabilities = f'{capabilities}[{ap["authentication"]}]'
                    channel = ap['channel']
                    rssi = ap['rssi']
                    self.__last_ap_reported.append({
                        "mac": mac,
                        "ssid": ssid,
                        "capabilities": capabilities,
                        "channel": channel,
                        "rssi": rssi
                    })
                    self.__session_reported.append((mac, ssid))
                    self.__db.add_wardrived_network(session_id = self.__session_id,
                                                    mac = mac,
                                                    ssid = ssid,
                                                    auth_mode = capabilities,
                                                    channel = channel,
                                                    rssi = rssi,
                                                    latitude = coordinates['latitude'],
                                                    longitude = coordinates['longitude'],
                                                    altitude = coordinates['altitude'],
                                                    accuracy = coordinates['accuracy'])
        else:
            self.__gps_available = False
            logging.warning("[WARDRIVER] GPS not available... skip wardriving log")
        
    def __upload_session_to_wigle(self, session_id):
        if self.__wigle_api_key != '':
            headers = {
                'Authorization': f'Basic {self.__wigle_api_key}',
                'Accept': 'application/json'
            }
            networks = self.__db.session_networks(session_id)
            csv = self.__csv_generator.networks_to_wigle_csv(networks)
            
            data = {
                'donate': 'on' if self.__wigle_donate else 'off'
            }

            file_form = {
                'file': (f'session_{session_id}.csv', csv)
            }

            try:
                response = requests.post(
                    url = 'https://api.wigle.net/api/v2/file/upload',
                    headers = headers,
                    data = data,
                    files = file_form,
                    timeout = 300
                )
                response.raise_for_status()
                self.__db.session_uploaded_to_wigle(session_id)
                logging.info(f'[WARDRIVER] Uploaded successfully session with id {session_id} on WiGLE')
                return True
            except Exception as e:
                logging.error(f'[WARDRIVER] Failed uploading session with id {session_id}: {e}')
                return False
        else:
            return False
    
    def on_internet_available(self, agent):
        if self.__wigle_enabled and not self.__lock.locked():
            with self.__lock:
                sessions_to_upload = self.__db.wigle_sessions_not_uploaded(self.__session_id)
                if len(sessions_to_upload) > 0:
                    logging.info(f'[WARDRIVER] Uploading previous sessions on WiGLE ({len(sessions_to_upload)} sessions) - current session will not be uploaded')

                    for session_id in sessions_to_upload:
                        self.__upload_session_to_wigle(session_id)
    
    def on_webhook(self, path, request):
        if request.method == 'GET':
            if path == '/' or not path:
                return render_template_string(HTML_PAGE, plugin_version = self.__version__)
            elif path == 'current-session':
                if self.__session_id == -1:
                    return json.dumps({
                        "id": -1,
                        "created_at": None,
                        "networks": None,
                        "last_ap_refresh": None,
                        "last_ap_reported": None
                    })
                else:
                    data = self.__db.current_session_stats(self.__session_id)
                    data['last_ap_refresh'] = self.__last_ap_refresh.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if self.__last_ap_refresh else None
                    data['last_ap_reported'] = self.__last_ap_reported
                    return json.dumps(data)
            elif path == 'general-stats':
                stats = self.__db.general_stats()
                stats['config'] = {
                    'wigle_enabled': self.__wigle_enabled,
                    'whitelist': self.__whitelist,
                    'db_path': self.__path,
                    'ui_enabled': self.__ui_enabled,
                    'wigle_api_key': self.__wigle_api_key
                }
                return json.dumps(stats)
            elif "csv/" in path:
                session_id = path.split('/')[-1]
                networks = self.__db.session_networks(session_id)
                csv = self.__csv_generator.networks_to_csv(networks)
                return csv
            elif path == 'sessions':
                sessions = self.__db.sessions()
                return json.dumps(sessions)
            elif 'upload/' in path:
                session_id = path.split('/')[-1]
                result = self.__upload_session_to_wigle(session_id)
                logging.info(result)
                return '{ "status": "Success" }' if result else'{ "status": "Error! Check the logs" }'
            elif path == 'networks':
                networks = self.__db.networks()
                return json.dumps(networks)
            elif path == 'map-networks':
                networks = self.__db.map_networks()
                return json.dumps(networks)
            else:
                abort(404)
        abort(404)

class WardriverIcon(Widget):
    def __init__(self, path, xy, reverse, color = 0):
        super().__init__(xy, color)
        self.image = Image.open(path)
        if(reverse):
            self.image = ImageOps.invert(self.image.convert('L'))

    def draw(self, canvas, drawer):
        canvas.paste(self.image, self.xy)

HTML_PAGE = '''
{% extends "base.html" %}
{% set active_page = "plugins" %}
{% block title %}
    Wardriver
{% endblock %}

{% block meta %}
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, user-scalable=0" />
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/datatables/1.10.21/css/jquery.dataTables.min.css" integrity="sha512-1k7mWiTNoyx2XtmI96o+hdjP8nn0f3Z2N4oF/9ZZRgijyV4omsKOXEnqL1gKQNPy2MTSP9rIEWGcH/CInulptA==" crossorigin="anonymous" referrerpolicy="no-referrer" />
    <link
        rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css"
    />
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" integrity="sha512-DTOQO9RWCH3ppGqcWaEA1BIZOC6xxalwEsw9c2QQeAIftl+Vegovlnee1c9QX4TctnWMn13TZye+giMm8e2LwA==" crossorigin="anonymous" referrerpolicy="no-referrer" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
        crossorigin=""/>

{% endblock %}

{% block styles %}
{{ super() }}
    <style>
        .container {
            margin-top: 10px;
            margin-bottom: 30px;
        }
        header i {
            font-size: 20px;
            margin-top: 10px;
            margin-right: 10px;
        }
        .center {
            text-align: center;
        }
        #menu {
            margin-top: 30px;
        }
        #menu div p {
            cursor: pointer;
        }
        .visible {
            display: initial;
        }
        .hidden {
            display: none;
        }
        #map_networks {
            height: 600px;
        }
        #sessions-table i {
            cursor: pointer;
            margin-right: 15px;
            font-size: 16px;
        }
        #manu-alert p {
            background-color: #fff5a5;
            padding: 10px 20px!important;
            text-align: center;
            margin: auto!important;
            border-radius: var(--pico-border-radius);
            color: #000;
            width: fit-content!important;
            margin-bottom: 20px!important;
        }
    </style>
{% endblock %}

{% block content %}
   <div class="container" data-theme="light">
        <header>
            <hgroup class="center">
                <h1>Wardriver plugin</h1>
                <p>v{{ plugin_version }} by <a href="https://github.com/cyberartemio/" target="_blank">cyberartemio</a></p>
                <a href="https://discord.gg/5vrJbbW3ve" target="_blank"><i class="fa-brands fa-discord"></i></a>
                <a href="https://github.com/cyberartemio/wardriver-pwnagotchi-plugin" target="_blank"><i class="fa-brands fa-github"></i></a>
            </hgroup>
        </header>
        <main>
            <div class="grid center" id="menu">
                <div>
                    <p id="menu-current-session"><a><i class="fa-solid fa-satellite-dish"></i> Current session</a></p>
                </div>
                <div>
                    <p id="menu-stats"><a><i class="fa-solid fa-chart-line"></i> Stats</a></p>
                </div>
                <div>
                    <p id="menu-sessions"><a><i class="fa-solid fa-table"></i> Sessions</a></p>
                </div>
                <div>
                    <p id="menu-networks"><a><i class="fa-solid fa-wifi"></i> Networks</a></p>
                </div>
                <div>
                    <p id="menu-map"><a><i class="fa-solid fa-map-location-dot"></i> Map</a></p>
                </div>
            </div>
            <div id="data-container">
                <div id="current-session">
                    <h3>Current session</h3>
                    <div id="manu-alert" class="hidden">
                        <p><i class="fa-solid fa-triangle-exclamation"></i> Pwnagotchi is in MANU mode, therefore currently it's not scanning. Restart in AUTO/AI mode to start a new wardriving session</p>
                    </div>
                    <div class="grid">
                        <div>
                            <article class="center">
                                <header>Session id</header>
                                <span id="current-session-id">-</span>
                            </article>
                        </div>
                        <div>
                            <article class="center">
                                <header>Started at </header>
                                <span id="current-session-start">-</span>
                            </article>
                        </div>
                        <div>
                            <article class="center">
                                <header>Networks count</header>
                                <span id="current-session-networks">-</span>
                            </article>
                        </div>
                        <div>
                            <article class="center">
                                <header>Last APs refresh</header>
                                <span id="current-session-last-update">-</span>
                            </article>
                        </div>
                    </div>
                    <h4>Last APs refresh networks</h4>
                    <div class="overflow-auto">
                        <table>
                            <thead>
                                <th scope="col">SSID</th>
                                <th scope="col">MAC</th>
                                <th scope="col">Channel</th>
                                <th scope="col">RSSI</th>
                                <th scope="col">Capabilities</th>
                            </thead>
                            <tbody id="current-session-table">
                                <tr><td colspan="5" class="center">No networks.</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <p class="center"><i>This page will automatically refresh every 30s</i></p>
                </div>
                <div id="stats">
                    <h3>Overall</h3>
                    <div class="grid">
                        <div>
                            <article class="center">
                                <header>Networks seen</header>
                                <span id="total-networks"></span>
                            </article>
                        </div>
                        <div>
                            <article class="center">
                                <header>Sessions count</header>
                                <span id="total-sessions"></span>
                            </article>
                        </div>
                        <div>
                            <article class="center">
                                <header>Sessions uploaded</header>
                                <span id="sessions-uploaded"></span>
                            </article>
                        </div>
                    </div>
                    <div class="grid">
                        <div>
                            <h3>Your WiGLE profile</h3>
                            <article>
                                <ul>
                                    <li><b>Username</b>: <span id="wigle-username">-</span></li>
                                    <li><b>Global rank</b>: #<span id="wigle-rank">-</span></li>
                                    <li><b>Month rank</b>: #<span id="wigle-month-rank">-</span></li>
                                    <li><b>Seen WiFi</b>: <span id="wigle-seen-wifi"></span></li>
                                    <li><b>Discovered WiFi</b>: <span id="wigle-discovered-wifi">-</span></li>
                                    <li><b>WiFi this month</b>: <span id="wigle-current-month-wifi">-</span></li>
                                    <li><b>WiFi previous month</b>: <span id="wigle-previous-month-wifi">-</span></li>
                                </ul>
                                <div id="wigle-badge" class="center"></div>
                            </article>
                        </div>
                        <div>
                            <h3>Current plugin config</h3>
                            <article>
                                <ul>
                                    <li><b>WiGLE automatic upload</b>: <span id="config-wigle">-</span></li>
                                    <li><b>UI enabled</b>: <span id="config-ui">-</span></li>
                                    <li><b>Database file path</b>: <span id="config-db">-</span></li>
                                    <li><b>Whitelist networks</b>:<ul id="config-whitelist"></ul></li>
                                </ul>
                            </article>
                        </div>
                    </div>
                </div>
                <div id="sessions">
                    <h3>Wardriving sessions</h3>
                    <p><b>Actions:</b><br />
                    <i class="fa-solid fa-file-csv"></i> : download session's CSV file<br />
                    <i class="fa-solid fa-cloud-arrow-up"></i> : upload session to WiGLE<br />
                    <!--<i class="fa-solid fa-trash"></i> : delete the session (<b>not the networks</b>)-->
                    </p>
                    <div class="overflow-auto">
                        <table>
                            <thead>
                                <th scope="col">ID</th>
                                <th scope="col">Date</th>
                                <th scope="col">Networks</th>
                                <th scope="col">Uploaded</th>
                                <th scope="col">Actions</th>
                            </thead>
                            <tbody id="sessions-table">
    
                            </tbody>
                        </table>
                    </div>
                </div>
                <div id="networks">
                    <h3>Networks</h3>
                    <div class="overflow-auto">
                        <table id="networks-table-container">
                            <thead>
                                <th scope="col">ID</th>
                                <th scope="col">MAC</th>
                                <th scope="col">SSID</th>
                                <th scope="col">First seen</th>
                                <th scope="col">First session ID</th>
                                <th scope="col">Last seen</th>
                                <th scope="col">Last session ID</th>
                                <th scope="col"># sessions</th>
                            </thead>
                            <tbody id="networks-table">
    
                            </tbody>
                        </table>
                    </div>
                </div>
                <div id="map">
                    <h3>Networks map</h3>
                    <p class="center"><i><i class="fa-solid fa-lightbulb"></i> Tip: click on a point to see the networks discovered there</i></p>
                    <div id="map_networks"></div>
                </div>
            </div>
        </main>
        <footer>

        </footer>
    </div>
{% endblock %}
{% block script %}
    </script>
    <!--<script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js" integrity="sha512-v2CJ7UaYy4JwqLDIrZUI/4hqeoQieOmAZNXBeQyjo21dadnwR+8ZaIJVT8EE2iyI61OV8e6M8PP2/4hpQINQ/g==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>-->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/datatables/1.10.21/js/jquery.dataTables.min.js" integrity="sha512-BkpSL20WETFylMrcirBahHfSnY++H2O1W+UnEEO4yNIl+jI2+zowyoGJpbtk6bx97fBXf++WJHSSK2MV4ghPcg==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
        crossorigin=""></script>
    <script src="https://unpkg.com/leaflet-canvas-marker@0.2.0"></script>
    <script>
    (function() {
        container = document.getElementById("data-container")
        setupMenuClickListeners()
        showCurrentSession()
        var map

        function downloadCSV(session_id) {
            request("GET", "/plugins/wardriver/csv/" + session_id, function(text) {
                const blob = new Blob([text], { type: 'text/csv' })

                // Creating an object for downloading url 
                const url = window.URL.createObjectURL(blob) 

                // Creating an anchor(a) tag of HTML 
                const a = document.createElement('a')

                // Passing the blob downloading url  
                a.setAttribute('href', url) 

                // Setting the anchor tag attribute for downloading 
                // and passing the download file name 
                a.setAttribute('download', 'session.csv')

                // Performing a download with click 
                a.click()
            })
        }

        function uploadSessionsToWigle(session_id) {
            request('GET', '/plugins/wardriver/upload/' + session_id, function(message) {
                showSessions()
                alert(message.status)
            })
        }

        function getCurrentSessionStats() {
            request('GET', "/plugins/wardriver/current-session", function(data) {
                if(data.id == -1) {
                    document.getElementById("manu-alert").className = 'visible'
                    document.getElementById("current-session-id").innerHTML = '-'
                    document.getElementById("current-session-networks").innerHTML = '-'
                    document.getElementById("current-session-last-update").innerHTML = '-'
                    document.getElementById("current-session-start").innerHTML = '-'
                    return
                }
                document.getElementById("manu-alert").className = 'hidden'
                document.getElementById("current-session-id").innerHTML = data.id
                document.getElementById("current-session-networks").innerHTML = data.networks
                document.getElementById("current-session-last-update").innerHTML = data.last_ap_refresh ? "<time class='timeago' datetime='" + parseUTCDate(data.last_ap_refresh).toISOString() + "'>-</time>" : "-"
                var sessionStartDate = parseUTCDate(data.created_at)
                document.getElementById("current-session-start").innerHTML = ("0" + sessionStartDate.getHours()).slice(-2) + ":" + ("0" + sessionStartDate.getMinutes()).slice(-2)
                var apTable = document.getElementById("current-session-table")
                apTable.innerHTML = ""
                if(data.last_ap_reported.length == 0) {
                    var tableRow = document.createElement('tr')
                    tableRow.innerHTML = "<td colspan='5' class='center'>No networks.</td>"
                    apTable.appendChild(tableRow)
                }
                else
                    for(var network of data.last_ap_reported) {
                        var tableRow = document.createElement('tr')
                        var macCol = document.createElement('td')
                        var ssidCol = document.createElement('td')
                        var channelCol = document.createElement('td')
                        var rssiCol = document.createElement('td')
                        var capabilitiesCol = document.createElement('td')
                        macCol.innerText = network.mac
                        ssidCol.innerText = network.ssid
                        channelCol.innerText = network.channel
                        rssiCol.innerText = network.rssi
                        capabilitiesCol.innerText = network.capabilities
                        tableRow.appendChild(macCol)
                        tableRow.appendChild(ssidCol)
                        tableRow.appendChild(channelCol)
                        tableRow.appendChild(rssiCol)
                        tableRow.appendChild(capabilitiesCol)
                        apTable.appendChild(tableRow)
                    }
                jQuery("time.timeago").timeago();
            })
        }

        setInterval(getCurrentSessionStats, 30 * 1000) // refresh current session data every 30s
        
        // Make HTTP request to pwnagotchi "server"
        function request(method, url, callback) {
            var xobj = new XMLHttpRequest();
            xobj.overrideMimeType("application/json")
            xobj.open(method, url, true);
            xobj.onreadystatechange = function () {
                if (xobj.readyState == 4 && xobj.status == "200") {
                    var response = xobj.responseText
                    try {
                        response = JSON.parse(xobj.responseText)
                    }
                    catch(error) {
                        
                    }
                    callback(response)
                }
            }
            xobj.send(null);
        }
        function loadWigleStats(api_key, callback) {
            var xobj = new XMLHttpRequest();
            xobj.overrideMimeType("application/json")
            xobj.open("GET", "https://api.wigle.net/api/v2/stats/user", true);
            xobj.setRequestHeader("Authorization", "Basic " + api_key)
            xobj.onreadystatechange = function () {
                if (xobj.readyState == 4 && xobj.status == "200") {
                    callback(JSON.parse(xobj.responseText))
                }
            }
            xobj.send(null);
        }
        function parseUTCDate(date) {
            var utcDateStr = date.replace(" ", "T")
            utcDateStr += ".000Z"
            return new Date(utcDateStr)
        }
        function updateContainerView(showing) {
            var views = [
                "current-session",
                "stats",
                "sessions",
                "networks",
                "map"
            ]

            $("#networks-table-container").DataTable().destroy();

            for(var view of views)
                document.getElementById(view).className = view == showing ? "visible" : "hidden"
        }
        function showCurrentSession() {
            updateContainerView("current-session")
            getCurrentSessionStats()
        }
        function showStats() {
            updateContainerView("stats")
            request('GET', "/plugins/wardriver/general-stats", function(data) {
                document.getElementById("total-networks").innerText = data.total_networks
                document.getElementById("total-sessions").innerText = data.total_sessions
                document.getElementById("sessions-uploaded").innerText = data.sessions_uploaded
                document.getElementById("config-wigle").innerText = data.config.wigle_enabled ? "enabled" : "disabled"
                document.getElementById("config-ui").innerText = data.config.ui_enabled
                document.getElementById("config-db").innerText = data.config.db_path
                document.getElementById("config-whitelist").innerHTML = ""
                if(data.config.whitelist.length == 0)
                    document.getElementById("config-whitelist").innerHTML = "none"
                else
                    for(var network of data.config.whitelist) {
                        var item = document.createElement("li")
                        item.innerText = network
                        document.getElementById("config-whitelist").appendChild(item)
                    }
                
                if(data.config.wigle_api_key) {
                    loadWigleStats(data.config.wigle_api_key, function(stats) {
                        document.getElementById("wigle-username").innerText = stats.user
                        document.getElementById("wigle-rank").innerText = stats.rank
                        document.getElementById("wigle-month-rank").innerText = stats.monthRank
                        document.getElementById("wigle-seen-wifi").innerText = stats.statistics.discoveredWiFi
                        document.getElementById("wigle-discovered-wifi").innerText = stats.statistics.discoveredWiFiGPS
                        document.getElementById("wigle-current-month-wifi").innerText = stats.statistics.eventMonthCount
                        document.getElementById("wigle-previous-month-wifi").innerText = stats.statistics.eventPrevMonthCount
                        document.getElementById("wigle-badge").innerHTML = "<img src='https://wigle.net" + stats.imageBadgeUrl +"' alt='wigle-profile-badge' />"
                    })
                }
            })
        }
        function showSessions() {
            updateContainerView("sessions")
            request('GET', "/plugins/wardriver/sessions", function(data) {
                var sessionsTable = document.getElementById("sessions-table")
                sessionsTable.innerHTML = ""
                for(var session of data) {
                    var tableRow = document.createElement("tr")
                    var idCol = document.createElement("td")
                    var createdCol = document.createElement("td")
                    var networksCol = document.createElement("td")
                    var wigleCol = document.createElement("td")
                    var actionsCol = document.createElement("td")

                    idCol.innerHTML = session.id
                    createdCol.innerHTML = session.created_at
                    networksCol.innerHTML = session.networks
                    wigleCol.innerHTML = "<i class='fa-regular " + (session.wigle_uploaded ? "fa-square-check" : "fa-square") + "'></i>"
                    csvIcon = document.createElement('i')
                    csvIcon.className = 'fa-solid fa-file-csv'
                    csvIcon.addEventListener("click", function(session_id) { return function() { downloadCSV(session_id)} } (session.id))
                    wigleIcon = document.createElement('i')
                    wigleIcon.className = 'fa-solid fa-cloud-arrow-up'
                    deleteIcon = document.createElement('i')
                    deleteIcon.className = 'fa-solid fa-trash'
                    actionsCol.appendChild(csvIcon)
                    if(!session.wigle_uploaded) {
                        wigleIcon.addEventListener("click", function(session_id) { return function() { uploadSessionsToWigle(session_id)} } (session.id))
                        actionsCol.appendChild(wigleIcon)
                    }
                    //actionsCol.appendChild(deleteIcon)
                    tableRow.appendChild(idCol)
                    tableRow.appendChild(createdCol)
                    tableRow.appendChild(networksCol)
                    tableRow.appendChild(wigleCol)
                    tableRow.appendChild(actionsCol)
                    sessionsTable.appendChild(tableRow)
                }
            })
        }
        function showNetworks() {
            updateContainerView("networks")
            request('GET', "/plugins/wardriver/networks", function(data) {
                $('#networks-table-container').DataTable({
                    data: data,
                    searching: false,
                    lengthChange: false,
                    pageLength: 25,
                    columns: [
                        { data: "id", width: "5%" },
                        { data: "mac", width: "15%" },
                        { data: "ssid", width: "20%" },
                        { data: "first_seen", width: "15%" },
                        { data: "first_session", width: "10%" },
                        { data: "last_seen", width: "15%" },
                        { data: "last_session", width: "10%" },
                        { data: "sessions_count", width: "10%" }
                    ]
                })
            })
        }
        function showMap() {
            updateContainerView("map")
            request('GET', '/plugins/wardriver/map-networks', function(networks) {
                if(map)
                    map.remove()
                map = L.map("map_networks", { center: [51.505, -0.09], zoom: 13, zoomControl: false})
                L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    maxZoom: 19,
                    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                }).addTo(map)
                var ciLayer = L.canvasIconLayer({}).addTo(map)
                var icon = L.icon({
                    iconUrl: 'https://img.icons8.com/metro/26/000000/marker.png',
                    iconSize: [20, 18],
                    iconAnchor: [10, 9]
                })

                var networksGrouped = networks.reduce(function (n, network) {
                    var key = network.latitude + "," + network.longitude
                    n[key] = n[key] || []
                    n[key].push(network)
                    return n
                }, Object.create(null))
                
                var markers = []
                var mapCenter
                Object.keys(networksGrouped).forEach(key => {
                    var networks = networksGrouped[key]
                    var coordinates = key.split(",")
                    if(!mapCenter)
                        mapCenter = coordinates
                    var popupText = ""
                    var popupCounter = 0
                    while(popupCounter < Math.min(networks.length, 7)) {
                        var network = networks[popupCounter]
                        if(network.ssid == "")
                            popupText += "<b>Hidden</b>"
                        else
                            popupText += "<b>" + network.ssid + "</b>"
                        
                        popupText += " (" + network.mac + ")<br />"
                        popupCounter++
                    }
                    if(networks.length > popupCounter)
                        popupText += '&plus;' + (networks.length - popupCounter) + ' more networks'
                    var marker = L.marker([coordinates[0], coordinates[1]], {icon: icon}).bindPopup(popupText)
                    markers.push(marker)
                })

                ciLayer.addLayers(markers)
                map.setView(mapCenter, 8)
            })
        }
        function setupMenuClickListeners() {
            document.getElementById("menu-current-session").addEventListener("click", showCurrentSession)
            document.getElementById("menu-stats").addEventListener("click", showStats)
            document.getElementById("menu-sessions").addEventListener("click", showSessions)
            document.getElementById("menu-networks").addEventListener("click", showNetworks)
            document.getElementById("menu-map").addEventListener("click", showMap)
        }
    })()
{% endblock %}
'''