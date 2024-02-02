import logging
import os
from datetime import datetime, timezone
import toml
import pwnagotchi.plugins as plugins

class Wardriver(plugins.Plugin):
    __author__ = 'CyberArtemio'
    __version__ = '1.0'
    __license__ = 'GPL3'
    __description__ = 'A wardriving plugin for pwnagotchi. Saves all networks seen and uploads data to Wigle.net once internet is available'

    DEFAULT_PATH = '/root/wardriver'

    def __init__(self):
        logging.debug('[WARDRIVER] Plugin created')
    
    def on_loaded(self):
        logging.info('[WARDRIVER] Plugin loaded')
        
        if 'whitelist' in self.options:
            self.__whitelist = self.options['whitelist']
            logging.info(f'[WARDRIVER] Ignoring {len(self.__whitelist)} networks')
        else:
            self.__whitelist = []
        
        if 'csv_path' in self.options:
            self.__csv_path = self.options['csv_path']
        else:
            self.__csv_path = self.DEFAULT_PATH
        
        if not os.path.exists(self.__csv_path):
            os.makedirs(self.__csv_path)
            logging.warning('[WARDRIVER] Created CSV directory')
        
        if 'wigle' in self.options:
            self.__wigle_enabled = self.options['wigle']['enabled'] if 'enabled' in self.options['wigle'] else False
            self.__wigle_api_key = self.options['wigle']['api_key'] if 'api_key' in self.options['wigle'] else None
            if self.__wigle_enabled and (not self.__wigle_api_key or self.__wigle_api_key == ''):
                logging.error('[WARDRIVER] Wigle enabled but no api key provided!')
                self.__wigle_enabled = False
        else:
            self.__wigle_enabled = False
            self.__wigle_api_key = None
        
        logging.info(f'[WARDRIVER] Saving session files inside {self.__csv_path}')
        
        if self.__wigle_enabled:
            logging.info('[WARDRIVER] Previous sessions will be uploaded to Wigle.net once internet is available')

        self.__new_wardriving_session()
    
    def __wigle_info(self):
        '''
        Return info used in CSV pre-header
        '''
        with open('/etc/pwnagotchi/config.toml', 'r') as config_file:
            data = toml.load(config_file)
            file_format = 'WigleWifi-1.4'
            app_release = self.__version__
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
            # Pwnagotchi name
            device = data['main']['name']
            # Pwnagotchi display model
            display = data['ui']['display']['type'] # Pwnagotchi display
            # CPU model
            try:
                with open('/proc/cpuinfo', 'r') as cpu_model:
                    board = cpu_model.read().split('\n')[1].split(':')[1][1:]
            except Exception:
                board = 'unknown'
            
            # Brand: currently set equal to model
            brand = model

            return {
                'file_format': file_format,
                'app_release': app_release,
                'model': model,
                'release': release,
                'device': device,
                'display': display,
                'board': board,
                'brand': brand
            }
 
    def __new_wardriving_session(self):
        self.ready = False
        now = datetime.now()
        self.__session_reported = []
        session_name = now.strftime('%Y-%m-%dT%H:%M:%S')
        session_file = os.path.join(self.__csv_path, f'{session_name}.csv')
        logging.info(f'[WARDRIVER] Initializing new session file {session_file}')
        self.__session_file = session_file
        try:
            with open(self.__session_file, 'w') as csv:
                # See: https://api.wigle.net/csvFormat.html
                # CSV pre-header
                preheader_data = self.__wigle_info()
                csv.write(f'{preheader_data["file_format"]},{preheader_data["app_release"]},{preheader_data["model"]},{preheader_data["release"]},{preheader_data["device"]},{preheader_data["display"]},{preheader_data["board"]},{preheader_data["brand"]}\n')
                # CSV header
                csv.write('MAC,SSID,AuthMode,FirstSeen,Channel,RSSI,CurrentLatitude,CurrentLongitude,AltitudeMeters,AccuracyMeters,Type\n')

                logging.info('[WARDRIVER] Session file initialized. Ready to wardrive!')
                self.ready = True
        except Exception as e:
            logging.critical(f'[WARDRIVER] Error while creating session file! {e}')

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
    
    def __ap_to_csv(self, ap, coordinates):
        bssid = ap['mac']
        ssid = ap['hostname'] if ap['hostname'] != '<hidden>' else ''
        capabilities = ''
        if ap['encryption'] != '':
            capabilities = f'{capabilities}[{ap["encryption"]}]'
        if ap['cipher'] != '':
            capabilities = f'{capabilities}[{ap["cipher"]}]'
        if ap['authentication'] != '':
            capabilities = f'{capabilities}[{ap["authentication"]}]'
        if ":" == ap['first_seen'][-3:-2]:
            ap['first_seen'] = ap['first_seen'][:-3] + ap['first_seen'][-2:] # Fix timezone parsing issue (see https://stackoverflow.com/questions/30999230/how-to-parse-timezone-with-colon)
            # Remove nanoseconds
            date_parts = ap['first_seen'].split('.')
            time_parts = date_parts[1].split('+')
            ap['first_seen'] = date_parts[0] + '+' + time_parts[1]
        first_timestamp_seen = datetime.strptime(ap['first_seen'], '%Y-%m-%dT%H:%M:%S%z').astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        channel = ap['channel']
        rssi = ap['rssi']
        latitude = coordinates['latitude']
        longitude = coordinates['longitude']
        altitude = coordinates['altitude']
        accuracy = coordinates['accuracy']
        type = 'WIFI'

        return f'{bssid},{ssid},{capabilities},{first_timestamp_seen},{channel},{rssi},{latitude},{longitude},{altitude},{accuracy},{type}\n'
    
    def __update_csv_file(self, aps, coordinates):
        with open(self.__session_file, '+a') as file:
            for ap in aps:
                try:
                    file.write(self.__ap_to_csv(ap, coordinates))
                    self.__session_reported.append((ap['mac'], ap['hostname']))
                except Exception as e:
                    logging.error(f'[WARDRIVER] Error while logging to csv file: {e}')

    def on_unfiltered_ap_list(self, agent, aps):
        info = agent.session()
        gps_data = info["gps"]

        # TODO: skip when in MANU mode?
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
                'accuracy': 10 # TODO: how can this be calculated?
            }

            filtered_aps = self.__filter_whitelist_aps(aps)
            filtered_aps = self.__filter_reported_aps(filtered_aps)

            if len(filtered_aps) > 0:
                logging.info(f'[WARDRIVER] Discovered {len(filtered_aps)} new networks')
                self.__update_csv_file(filtered_aps, coordinates)
        else:
            logging.warning("[WARDRIVER] GPS not available... skip wardriving log")
        
    def on_internet_available(self, agent):
        # TODO: implement uploading to Wigle.net
        pass