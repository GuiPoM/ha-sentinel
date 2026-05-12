"""Test configuration and shared fixtures for ha-sentinel."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

# Ensure custom_components is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield
