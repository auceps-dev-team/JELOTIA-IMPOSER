import json
from pathlib import Path

CONFIG_FILE = Path("config.json")

DEFAULT_CONFIG = {
    "paths": {
        "input": "",
        "output": "",
        "archive": "",
        "logs": ""
    },
    "imposition": {
        "sheet_width": 320,
        "sheet_height": 450,
        "spacing": 5,
        "rotation_allowed": True
    },
    "preflight": {
        "min_dpi": 300,
        "allowed_formats": "A4, A5, B2"
    },
    "export": {
        "format": "PDF",
        "resolution": 300,
        "icc_profile": "Coated FOGRA39"
    },
    "users": {
        "role": "Admin"
    },
    "automation": {
        "group_delay_minutes": 5,
        "max_files_per_job": 50,
        "scheduled_time": "",  # e.g., "20:00"
        "enable_scheduling": False
    },
    "performance": {
        "workers": 4,
        "memory_limit_mb": 4096
    }
}

class ConfigManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance.config = DEFAULT_CONFIG.copy()
            cls._instance.load()
        return cls._instance

    def load(self, path=None):
        file_path = Path(path) if path else CONFIG_FILE
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Deep update to preserve defaults for missing keys
                    for key, value in data.items():
                        if isinstance(value, dict) and key in self.config:
                            self.config[key].update(value)
                        else:
                            self.config[key] = value
            except Exception as e:
                print(f"Error loading config: {e}")

    def save(self, path=None):
        file_path = Path(path) if path else CONFIG_FILE
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")
            
    def get(self, section, key=None):
        if key:
            return self.config.get(section, {}).get(key)
        return self.config.get(section)
        
    def set(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value
