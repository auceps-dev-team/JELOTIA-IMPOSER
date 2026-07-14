import logging
from pathlib import Path
from typing import List, Optional

from src.core.models.domain import ProductPreset

logger = logging.getLogger(__name__)


class PresetStore:
    """JSON persistence for ProductPresets under <HotFolder>/Presets — same
    contract as TemplateStore: one file per preset, archived ones hidden from
    pickers but kept on disk."""

    def __init__(self, directory: Optional[Path] = None):
        if directory is None:
            from src.utils.config import config

            directory = Path(config.base_dir) / "Presets"
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _json_path(self, preset_id) -> Path:
        return self.directory / f"{preset_id}.json"

    def save(self, preset: ProductPreset) -> ProductPreset:
        self._json_path(preset.id).write_text(
            preset.model_dump_json(indent=2), encoding="utf-8"
        )
        return preset

    def load(self, preset_id) -> ProductPreset:
        raw = self._json_path(preset_id).read_text(encoding="utf-8")
        return ProductPreset.model_validate_json(raw)

    def list(self, include_archived: bool = False) -> List[ProductPreset]:
        presets: List[ProductPreset] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                presets.append(
                    ProductPreset.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except Exception as e:
                logger.warning(f"Gamme illisible ({path.name}): {e}")
        if not include_archived:
            presets = [p for p in presets if not p.archived]
        return sorted(presets, key=lambda p: p.name.lower())

    def delete(self, preset_id) -> None:
        self._json_path(preset_id).unlink(missing_ok=True)

    def set_archived(self, preset_id, archived: bool) -> None:
        preset = self.load(preset_id)
        preset.archived = archived
        self.save(preset)
