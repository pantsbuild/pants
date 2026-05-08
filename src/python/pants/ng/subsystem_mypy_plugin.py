# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Mypy plugin that suppresses 'empty-body' errors for methods decorated with @option."""

# from __future__ import annotations

from typing import Type

from mypy.nodes import (
    IS_ABSTRACT,
    ClassDef,
    Decorator,
    FuncDef,
    Statement,
)
from mypy.plugin import ClassDefContext, Plugin


def _has_option_decorator(node: Decorator) -> bool:
    for dec in node.decorators:
        if hasattr(dec, "callee"):
            if hasattr(dec.callee, "name") and dec.callee.name == "option":
                return True
    return False


def _process_defns(defns: list[Statement]) -> None:
    """Process class/function definitions."""
    for defn in defns:
        if isinstance(defn, ClassDef):
            _process_defns(defn.defs.body)
        elif isinstance(defn, FuncDef):
            _process_defns(defn.body.body)
        elif isinstance(defn, Decorator):
            if _has_option_decorator(defn):
                # Mark func as abstract, so mypy doesn't complain about its empty body.
                # Note that this will make mypy complain about instantiating an abstract class
                # if we call __init__() directly, hence the `SubsystemNg.create()` classmethod.
                defn.func.abstract_status = IS_ABSTRACT
            else:
                _process_defns(defn.func.body.body)


def _process_subclass_hook(ctx: ClassDefContext) -> None:
    _process_defns(ctx.cls.defs.body)


# NB: If we create more intermediate subclasses, they must be added here.
_SUBSYSTEM_BASE_CLASSES = frozenset(
    {
        "pants.ng.subsystem.SubsystemNg",
        "pants.ng.subsystem.UniversalSubsystem",
        "pants.ng.subsystem.ContextualSubsystem",
        "pants.ng.goal.GoalSubsystemNg",
    }
)


class SubsystemPlugin(Plugin):
    """Mypy plugin that processes SubsystemNg subclasses to find methods decorated with @option."""

    def get_base_class_hook(self, fullname: str):
        if fullname in _SUBSYSTEM_BASE_CLASSES:
            return _process_subclass_hook
        return None


def plugin(version: str) -> Type[Plugin]:
    return SubsystemPlugin
