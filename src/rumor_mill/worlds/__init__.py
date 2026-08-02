"""Authored world packages and loading contracts."""

from rumor_mill.worlds.authoring import WorldDefinition, WorldLoadError, load_world
from rumor_mill.worlds.continuity import validate_continuity
from rumor_mill.worlds.town_state import PublicPresence, TownState

__all__ = [
    "PublicPresence",
    "TownState",
    "WorldDefinition",
    "WorldLoadError",
    "load_world",
    "validate_continuity",
]
