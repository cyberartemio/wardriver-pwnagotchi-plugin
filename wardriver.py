import logging
import sqlite3
import os
from datetime import datetime, timezone
import toml
import pwnagotchi.plugins as plugins
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK
import pwnagotchi.ui.fonts as fonts
from threading import Lock
import requests

class Database():
    def __init__(self, path):
        self.__path = path
        self.__db_connect()
        self.remove_empty_sessions() # Remove old sessions that don't have networks
    
    def __db_connect(self):
        logging.info('[WARDRIVER] Setting up database connection...')
        self.__connection = sqlite3.connect(self.__path, check_same_thread = False, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        self.__cursor = self.__connection.cursor()
        self.__cursor.execute('CREATE TABLE IF NOT EXISTS sessions ("id" INTEGER, "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "wigle_uploaded" INTEGER DEFAULT 0, PRIMARY KEY("id" AUTOINCREMENT))') # sessions table contains wardriving sessions
        self.__cursor.execute('CREATE TABLE IF NOT EXISTS networks ("id" INTEGER, "mac" TEXT NOT NULL, "ssid" TEXT, PRIMARY KEY ("id" AUTOINCREMENT))') # networks table contains seen networks without coordinates/sessions info
        self.__cursor.execute('CREATE TABLE IF NOT EXISTS wardrive ("id" INTEGER, "session_id" INTEGER NOT NULL, "network_id" INTEGER NOT NULL, "auth_mode" TEXT NOT NULL, "latitude" TEXT NOT NULL, "longitude" TEXT NOT NULL, "altitude" TEXT NOT NULL, "accuracy" INTEGER NOT NULL, "channel" INTEGER NOT NULL, "rssi" INTEGER NOT NULL, "seen_timestamp" TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY("id" AUTOINCREMENT), FOREIGN KEY("session_id") REFERENCES sessions("id"), FOREIGN KEY("network_id") REFERENCES networks("id"))') # wardrive table contains the relations between sessions and networks with timestamp and coordinates
        self.__connection.commit()
        logging.info('[WARDRIVER] Succesfully connected to db')
    
    def disconnect(self):
        self.__cursor.close()
        self.__connection.commit()
        self.__connection.close()
        logging.info('[WARDRIVER] Closed db connection')

    def import_session(self, session_name, session_networks):
        pass

    def new_wardriving_session(self):
        self.__cursor.execute('INSERT INTO sessions DEFAULT VALUES') # using default values
        session_id = self.__cursor.lastrowid
        self.__connection.commit()
        return session_id
    
    def add_wardrived_network(self, session_id, mac, ssid, auth_mode, latitude, longitude, altitude, accuracy, channel, rssi):
        self.__cursor.execute('SELECT id FROM networks WHERE mac = ? AND ssid = ?', [mac, ssid])
        network = self.__cursor.fetchone()
        network_id = network[0] if network else None
        if(not network_id):
            self.__cursor.execute('INSERT INTO networks(mac, ssid) VALUES (?, ?)', [mac, ssid])
            network_id = self.__cursor.lastrowid
        
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
        return f'{network["mac"]},{network["ssid"]},{network["seen_timestamp"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")},{network["channel"]},{network["rssi"]},{network["latitude"]},{network["longitude"]},{network["altitude"]},{network["accuracy"]},WIFI\n'

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
    __version__ = '1.1'
    __license__ = 'GPL3'
    __description__ = 'A wardriving plugin for pwnagotchi. Saves all networks seen and uploads data to WiGLE once internet is available'

    DEFAULT_PATH = '/root/wardriver' # SQLite database default path
    DATABASE_NAME = 'wardriver.db' # SQLite database file name

    def __init__(self):
        logging.debug('[WARDRIVER] Plugin created')
    
    def on_loaded(self):
        logging.info('[WARDRIVER] Plugin loaded (join the Discord server: https://discord.gg/5vrJbbW3ve)')

        self.__lock = Lock()
        
        if 'whitelist' in self.options:
            self.__whitelist = self.options['whitelist']
        else:
            self.__whitelist = []

        self.__load_global_whitelist()
        
        if 'path' in self.options:
            self.__path = self.options['path']
        else:
            self.__path = self.DEFAULT_PATH
        
        if 'ui' in self.options:
            self.__ui_enabled = self.options['ui']['enabled'] if 'enabled' in self.options['ui'] else False
            try:
                self.__ui_position = (self.options['ui']['position']['x'], self.options['ui']['position']['y'])
            except Exception:
                self.__ui_position = (5, 95)
        else:
            self.__ui_enabled = False
            self.__ui_position = (0, 0)
                
        if 'wigle' in self.options:
            self.__wigle_enabled = self.options['wigle']['enabled'] if 'enabled' in self.options['wigle'] else False
            self.__wigle_api_key = self.options['wigle']['api_key'] if 'api_key' in self.options['wigle'] else None
            self.__wigle_donate = self.options['wigle']['donate'] if 'donate' in self.options['wigle'] else False
            if self.__wigle_enabled and (not self.__wigle_api_key or self.__wigle_api_key == ''):
                logging.error('[WARDRIVER] Wigle enabled but no api key provided!')
                self.__wigle_enabled = False
        else:
            self.__wigle_enabled = False
            self.__wigle_api_key = None
            self.__wigle_donate = False
        
        if not os.path.exists(self.__path):
            os.makedirs(self.__path)
            logging.warning('[WARDRIVER] Created db directory')
        
        self.__db = Database(os.path.join(self.__path, self.DATABASE_NAME))
        self.__csv_generator = CSVGenerator()
        self.__session_reported = []
        self.ready = True

        logging.info(f'[WARDRIVER] Saving session files inside {self.__path}')
        
        if self.__wigle_enabled:
            logging.info('[WARDRIVER] Previous sessions will be uploaded to WiGLE once internet is available')
            logging.info('[WARDRIVER] Join the WiGLE group: search "The crew of the Black Pearl" and start wardriving with us!')

        self.__session_id = self.__db.new_wardriving_session()

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
    
    def on_ui_setup(self, ui):
        if self.__ui_enabled:
            logging.info('[WARDRIVER] Adding status text to ui')
            ui.add_element('wardriver', LabeledValue(color = BLACK,
                                               label = 'wardrive:',
                                               value = "- nets",
                                               position = self.__ui_position,
                                               label_font = fonts.Small,
                                               text_font = fonts.Small))

    def on_ui_update(self, ui):
        if self.__ui_enabled and self.ready:
            ui.set('wardriver', f'{self.__db.session_networks_count(self.__session_id)} net')

    def on_unload(self, ui):
        if self.__ui_enabled:
            with ui._lock:
                ui.remove_element('wardriver')
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
            logging.warning("[WARDRIVER] GPS not available... skip wardriving log")
        
    def on_internet_available(self, agent):
        if self.__wigle_enabled and not self.__lock.locked():
            with self.__lock:
                sessions_to_upload = self.__db.wigle_sessions_not_uploaded(self.__session_id)
                if len(sessions_to_upload) > 0:
                    logging.info(f'[WARDRIVER] Uploading previous sessions on WiGLE ({len(sessions_to_upload)} sessions) - current session will not be uploaded')
                    headers = {
                        'Authorization': f'Basic {self.__wigle_api_key}',
                        'Accept': 'application/json'
                    }

                    for session_id in sessions_to_upload:
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
                        except Exception as e:
                            logging.error(f'[WARDRIVER] Failed uploading session with id {session_id}: {e}')
                            continue
    
    def on_webhook(self, path, request):
        pass
