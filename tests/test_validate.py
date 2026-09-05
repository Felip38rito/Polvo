"""Tests for the polvo CLI config validation (validate.py)."""
from __future__ import annotations

from pathlib import Path

import yaml

from polvo_cli import validate


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def test_missing_config_returns_none(tmp_path: Path):
    assert validate.load_config(tmp_path / "nope.yml") is None


def test_invalid_yaml_returns_none(tmp_path: Path):
    p = tmp_path / "bad.yml"
    p.write_text("tiers: [unclosed")
    assert validate.load_config(p) is None


def test_empty_config_problems(tmp_path: Path):
    p = _write(tmp_path, {"providers": {}, "tiers": {}})
    problems = validate.config_problems(p)
    assert any("No providers" in x for x in problems)
    assert any("No tiers" in x for x in problems)
    assert any("Classifier" in x for x in problems)


def test_missing_config_problems(tmp_path: Path):
    problems = validate.config_problems(tmp_path / "nope.yml")
    assert len(problems) == 1
    assert "No config found" in problems[0]


def test_providers_only_missing_tiers_and_classifier(tmp_path: Path):
    p = _write(tmp_path, {"providers": {"A": {"base_url": "https://x/v1"}}})
    problems = validate.config_problems(p)
    assert not any("No providers" in x for x in problems)
    assert any("No tiers" in x for x in problems)
    assert any("Classifier" in x for x in problems)


def test_complete_config_ready(tmp_path: Path):
    p = _write(
        tmp_path,
        {
            "providers": {"A": {"base_url": "https://x/v1", "api_key_env": "K"}},
            "tiers": {"mini": {"model": "m", "provider": "A"}},
            "classifier": {"model": "m", "provider": "A"},
        },
    )
    assert validate.config_problems(p) == []
    assert validate.is_ready(p) is True


def test_classifier_without_model_not_ready(tmp_path: Path):
    p = _write(
        tmp_path,
        {
            "providers": {"A": {"base_url": "https://x/v1"}},
            "tiers": {"mini": {"model": "m", "provider": "A"}},
            "classifier": {"provider": "A"},
        },
    )
    assert validate.is_ready(p) is False
    assert any("Classifier" in x for x in validate.config_problems(p))
