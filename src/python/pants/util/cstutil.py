# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.util
import logging
from typing import Union

import libcst as cst
import libcst.matchers as m

logger = logging.getLogger(__name__)


def make_importfrom(module: str, func: str) -> cst.ImportFrom:
    """Generates a cst.ImportFrom from a module and function string."""
    return cst.ImportFrom(
        module=make_importfrom_attr(module), names=[cst.ImportAlias(cst.Name(func))]
    )


def make_importfrom_attr(module: str) -> cst.Attribute | cst.Name:
    """Generates a cst.Attribute or cst.Name from a module string."""
    parts = module.split(".")
    if len(parts) == 1:
        return cst.Name(parts[0])

    partial_module = ".".join(parts[:-1])
    return cst.Attribute(value=make_importfrom_attr(partial_module), attr=cst.Name(parts[-1]))


def make_importfrom_attr_matcher(module: str) -> Union[m.Attribute, m.Name]:
    """Generates a cst matcher.Attribute or matcher.Name from a module string."""
    parts = module.split(".")
    if len(parts) == 1:
        return m.Name(parts[0])

    partial_module = ".".join(parts[:-1])
    return m.Attribute(value=make_importfrom_attr_matcher(partial_module), attr=m.Name(parts[-1]))


def extract_functiondef_from_module(module: str, func: str) -> cst.FunctionDef | None:
    """Parse the file associated with the module return `func` as a FunctionDef."""
    if not (spec := importlib.util.find_spec(module)):
        logger.warning(f"Failed to find module {module}")
        return None

    assert spec.origin is not None
    with open(spec.origin) as f:
        source_code = f.read()
        tree = cst.parse_module(source_code)
        results = m.findall(tree, matcher=m.FunctionDef(m.Name(func), asynchronous=m.Asynchronous()))
        return cst.ensure_type(results[0], cst.FunctionDef) if results else None
