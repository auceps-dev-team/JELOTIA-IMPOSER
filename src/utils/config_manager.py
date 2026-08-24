import copy
import json
import shutil
import sys
from pathlib import Path


def _bundled_config_path() -> Path:
    """Where the shipped default config.json lives: inside the PyInstaller
    bundle (sys._MEIPASS, e.g. .../_internal/config.json) when frozen, or the
    project root when running from source."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parents[2]
    return base / "config.json"


# Config.json is looked up relative to the current working directory when
# running from source, which is CWD when double-clicking the exe — that's the
# folder next to JelotiaImposer.exe, NOT the bundled _internal/config.json one
# level below it, and it's also not writable without admin rights once
# installed under Program Files. So the *live, editable* config always lives
# under the user's Jelotia data folder (matching the base dir already used
# for HotFolder/Processing/etc. in src/utils/config.py), seeded on first run
# from whichever config.json shipped with this build.
CONFIG_FILE = Path.home() / "Jelotia" / "config.json"

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
    "output": {
        "archive_days": 15,
        "enable_notifications": True
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
            # deepcopy, not copy(): a shallow copy shares every sub-dict with
            # the module constant, so load()'s `self.config[key].update(...)`
            # and every set() rewrote DEFAULT_CONFIG in place — destroying the
            # factory-defaults fallback from the first write onwards.
            cls._instance.config = copy.deepcopy(DEFAULT_CONFIG)
            cls._instance.load()
        return cls._instance

    def load(self, path=None):
        file_path = Path(path) if path else CONFIG_FILE
        if not file_path.exists() and path is None:
            # First run: seed the user's live config from whichever
            # config.json shipped with this build (bundled default under
            # _internal/ when frozen, or the repo's own when running from source).
            self._seed_from_bundled_default(file_path)
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
                if sys.stdout is not None:
                    print(f"Error loading config: {e}")

    def _seed_from_bundled_default(self, dest: Path) -> None:
        bundled = _bundled_config_path()
        if not bundled.exists() or bundled == dest:
            return
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled, dest)
        except Exception as e:
            if sys.stdout is not None:
                print(f"Error seeding default config: {e}")

    def save(self, path=None):
        file_path = Path(path) if path else CONFIG_FILE
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            if sys.stdout is not None:
                print(f"Error saving config: {e}")
            
    def get(self, section, key=None):
        if key:
            return self.config.get(section, {}).get(key)
        return self.config.get(section)
        
    def set(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value
