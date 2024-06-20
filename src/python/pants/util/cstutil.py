# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

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
