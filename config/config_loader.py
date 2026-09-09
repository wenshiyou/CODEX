"""
配置加载与管理模块
"""
import json
import os
from pathlib import Path


class Config:
    _instance = None
    _data = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        config_path = Path(__file__).parent / "config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self._data = {}

    def get(self, key, default=None):
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key, value):
        keys = key.split(".")
        d = self._data
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value
        self._save()

    def _save(self):
        config_path = Path(__file__).parent / "config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    @property
    def data(self):
        return self._data
