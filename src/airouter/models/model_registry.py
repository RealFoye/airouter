"""ModelRegistry：从 models.yaml 加载模型配置，提供按 tier/name 查找。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from airouter.config import ModelEntry, ModelsConfig, load_models


class ModelRegistry:
    def __init__(self, config: ModelsConfig):
        self._models = config.models
        self._by_name = {m.name: m for m in self._models}
        self._by_tier: dict[int, list[ModelEntry]] = {}
        for m in self._models:
            self._by_tier.setdefault(m.tier, []).append(m)

    @property
    def all_models(self) -> list[ModelEntry]:
        return list(self._models)

    def get_by_name(self, name: str) -> Optional[ModelEntry]:
        return self._by_name.get(name)

    def get_by_tier(self, tier: int) -> list[ModelEntry]:
        return self._by_tier.get(tier, [])

    def get_all_tiers(self) -> list[int]:
        return sorted(self._by_tier.keys())

    def get_tier1_models(self) -> list[ModelEntry]:
        return self.get_by_tier(1)

    def get_tier2_models(self) -> list[ModelEntry]:
        return self.get_by_tier(2)

    def get_tier3_models(self) -> list[ModelEntry]:
        return self.get_by_tier(3)

    def __len__(self) -> int:
        return len(self._models)

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __repr__(self) -> str:
        names = [m.name for m in self._models]
        return f"ModelRegistry({names})"


@lru_cache(maxsize=1)
def get_registry(data_dir: Optional[Path] = None) -> ModelRegistry:
    config = load_models(data_dir)
    return ModelRegistry(config)
