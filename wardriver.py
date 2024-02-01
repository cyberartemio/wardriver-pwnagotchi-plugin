import logging
import pwnagotchi.plugins as plugins

class Wardriver(plugins.Plugin):
    __author__ = 'CyberArtemio'
    __version__ = '1.0'
    __license__ = 'GPL3'
    __description__ = 'A wardriving plugin for pwnagotchi. Saves all networks seen and uploads data to Wigle.net once internet is available'

    def __init__(self):
        logging.debug('[WARDRIVER] Plugin created')
    
    def on_loaded(self):
        logging.info('[WARDRIVER] Plugin loaded')
    
    def on_unfiltered_ap_list(self, agent, aps):
        logging.debug(f'[WARDRIVER] Discovered {len(aps)} networks')
        
    def on_internet_available(self, agent):
        logging.info('[WARDRIVER] Uploading wardriving session files to Wigle.net...')