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
    MypyFile,
    Statement,
)
from mypy.plugin import Plugin


def _has_option_decorator(node: Decorator) -> bool:
    for dec in node.decorators:
        if hasattr(dec, "callee"):
            if hasattr(dec.callee, "name") and dec.callee.name == "option":
                return True
    return False


def _process_defns(defns: list[Statement]) -> None:
    """Process definitions."""
    for defn in defns:
        if isinstance(defn, ClassDef):
            _process_defns(defn.defs.body)
        elif isinstance(defn, FuncDef):
            _process_defns(defn.body.body)
        elif isinstance(defn, Decorator):
            if _has_option_decorator(defn):
                defn.func.abstract_status = IS_ABSTRACT
            else:
                _process_defns(defn.func.body.body)


class SubsystemPlugin(Plugin):
    """Mypy plugin that processes files to find methods decorated with @option."""

    def get_additional_deps(self, file: MypyFile) -> list[tuple[int, str, int]]:
        _process_defns(file.defs)
        return []


def plugin(version: str) -> Type[Plugin]:
    return SubsystemPlugin
