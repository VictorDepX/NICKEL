"""Todas as skills. Para adicionar uma: crie o módulo com `register(registry)` e inclua em SKILL_MODULES."""

from __future__ import annotations

from nickel.core.skills import ToolRegistry
from nickel.skills import google, memory, music, notes, reminders, spotify

SKILL_MODULES = (spotify, music, notes, reminders, google, memory)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for module in SKILL_MODULES:
        module.register(registry)
    return registry
