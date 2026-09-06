"""Tests for polvo_cli/core.py — centralized config I/O."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from polvo_cli import core


def test_config_path_points_to_user_config(monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: Path("/tmp/fake-home"))
    assert core.config_path() == Path("/tmp/fake-home") / ".polvo" / "config.yml"


def test_load_config_missing_returns_empty(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(core, "config_path", lambda: tmp_path / "nope.yml")
    assert core.load_config() == {"providers": {}, "adaptive": {}, "custom": {}}


def test_load_config_invalid_yaml_returns_empty(monkeypatch, tmp_path: Path):
    bad = tmp_path / "bad.yml"
    bad.write_text("adaptive: [unclosed")
    monkeypatch.setattr(core, "config_path", lambda: bad)
    assert core.load_config() == {"providers": {}, "adaptive": {}, "custom": {}}


def test_load_config_non_mapping_returns_empty(monkeypatch, tmp_path: Path):
    not_map = tmp_path / "list.yml"
    not_map.write_text("- a\n- b\n")
    monkeypatch.setattr(core, "config_path", lambda: not_map)
    assert core.load_config() == {"providers": {}, "adaptive": {}, "custom": {}}


def test_load_config_explicit_path(tmp_path: Path):
    p = tmp_path / "elsewhere.yml"
    p.write_text(yaml.safe_dump({"providers": {"A": {"base_url": "https://x/v1"}}}))
    data = core.load_config(p)
    assert data["providers"]["A"]["base_url"] == "https://x/v1"


def test_save_config_writes_yaml(monkeypatch, tmp_path: Path):
    target = tmp_path / "config.yml"
    monkeypatch.setattr(core, "config_path", lambda: target)
    payload = {"providers": {}, "adaptive": {}, "custom": {}}
    core.save_config(payload)
    assert target.exists()
    assert yaml.safe_load(target.read_text()) == payload


def test_save_config_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "sub" / "dir" / "config.yml"
    core.save_config({"a": 1}, path=target)
    assert target.exists()
    assert yaml.safe_load(target.read_text()) == {"a": 1}


def test_save_config_explicit_path_beats_default(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(core, "config_path", lambda: tmp_path / "default.yml")
    explicit = tmp_path / "explicit.yml"
    core.save_config({"b": 2}, path=explicit)
    assert explicit.exists()
    assert not (tmp_path / "default.yml").exists()