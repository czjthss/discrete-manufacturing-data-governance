"""Core modules for the discrete-manufacturing data governance system."""

from . import (
    indicator_3_1,
    indicator_3_2,
    indicator_3_3,
    indicator_3_4,
    indicator_3_5,
    indicator_3_6,
    indicator_3_7,
    indicator_3_8,
    indicator_3_9,
)
from .integration_registry import INTEGRATION_REGISTRY

INDICATORS = {
    "3.1": indicator_3_1,
    "3.2": indicator_3_2,
    "3.3": indicator_3_3,
    "3.4": indicator_3_4,
    "3.5": indicator_3_5,
    "3.6": indicator_3_6,
    "3.7": indicator_3_7,
    "3.8": indicator_3_8,
    "3.9": indicator_3_9,
}
