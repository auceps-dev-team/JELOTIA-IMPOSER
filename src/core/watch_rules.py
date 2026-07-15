"""Watch rules: one hot folder per product preset.

A single input folder forces the operator to re-pick settings for every order.
Binding a folder to a gamme turns the drop itself into the instruction:
`.../HotFolder/Badges A7/` produces badge jobs, `.../Vinyle/` vinyl jobs — no
click, which is what "24/7 unattended" actually requires.

Rules live in config.json (automation.watch_rules) rather than a separate
store: they are configuration, and they must be readable before anything else
starts.
"""

import logging
from pathlib import Path
from typing import List, Optional

from src.core.models.domain import JobSettings, WatchRule

logger = logging.getLogger(__name__)

_SECTION = "automation"
_KEY = "watch_rules"


def load_rules() -> List[WatchRule]:
    """Every configured rule, invalid entries skipped rather than fatal."""
    from src.utils.config_manager import ConfigManager

    raw = ConfigManager().get(_SECTION, _KEY) or []
    rules: List[WatchRule] = []
    for entry in raw:
        try:
            rules.append(WatchRule.model_validate(entry))
        except Exception as e:
            logger.warning(f"Règle de surveillance illisible ({entry}) : {e}")
    return rules


def save_rules(rules: List[WatchRule]) -> None:
    from src.utils.config_manager import ConfigManager

    config = ConfigManager()
    config.set(_SECTION, _KEY, [r.model_dump(mode="json") for r in rules])
    config.save()


def active_rules() -> List[WatchRule]:
    """Enabled rules whose folder is actually set."""
    return [r for r in load_rules() if r.enabled and r.folder.strip()]


def settings_for_rule(rule: Optional[WatchRule], fallback: JobSettings) -> JobSettings:
    """The settings a job from this rule must use: the bound preset's recipe,
    or `fallback` (global settings) when the rule has no preset or it can no
    longer be read — never silently produce with the wrong recipe."""
    if rule is None or not rule.preset_id:
        return fallback
    try:
        from src.core.presets import PresetStore

        return PresetStore().load(rule.preset_id).settings.model_copy()
    except Exception as e:
        logger.warning(
            f"Gamme introuvable pour la règle « {rule.name} » ({e}) — "
            "réglages globaux utilisés"
        )
        return fallback


def ensure_folders(rules: List[WatchRule]) -> None:
    """Creates the watched folders so the operator can drop files right away."""
    for rule in rules:
        try:
            Path(rule.folder).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Dossier surveillé impossible ({rule.folder}) : {e}")
