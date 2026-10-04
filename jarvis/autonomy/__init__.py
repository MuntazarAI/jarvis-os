"""Autonomy & presence facades (1.0). Thin composition over existing systems."""

from .organize import CAPABILITY as ORGANIZE_CAPABILITY
from .organize import execute as organize_execute
from .organize import plan as organize_plan
from .perceive import correlate as correlate_observations
from .preferences import observe_choice, set_preference
from .presence import PresenceRuntime

__all__ = ["ORGANIZE_CAPABILITY", "PresenceRuntime",
           "correlate_observations", "observe_choice",
           "organize_execute", "organize_plan", "set_preference"]
