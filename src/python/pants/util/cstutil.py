# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib.util
import logging
from typing import Union

import libcst as cst
import libcst.matchers as m

logger = logging.getLogger(__name__)

def make_import_from(module: str, func: str) -> cst.ImportFrom:
    """Manually generating ImportFrom using Attributes is tricky, parse a string instead."""
    return cst.ImportFrom(
        module=_make_importfrom_attr(module), names=[cst.ImportAlias(cst.Name(func))]
    )


def _make_importfrom_attr(module: str) -> cst.Attribute | cst.Name:
    parts = module.split(".")
    if len(parts) == 1:
        return cst.Name(parts[0])

    partial_module = ".".join(parts[:-1])
    return cst.Attribute(value=_make_importfrom_attr(partial_module), attr=cst.Name(parts[-1]))


def make_importfrom_attr_matcher(module: str) -> Union[m.Attribute, m.Name]:
    """Build matcher for a module given sequence of import parts."""
    parts = module.split(".")
    if len(parts) == 1:
        return m.Name(parts[0])

    partial_module = ".".join(parts[:-1])
    return m.Attribute(value=make_importfrom_attr_matcher(partial_module), attr=m.Name(parts[-1]))


def remove_unused_implicitly(call: cst.Call, called_func: cst.FunctionDef) -> cst.Call:
    """The CallByNameSyntaxMapper aggressively adds `implicitly` for safety. This function removes
    unnecessary ones.

    The following cases are handled:
    - The called function takes no arguments
    - TODO: The called function takes the same number of arguments that are passed to it
    - TODO: Check the types of the passed in parameters, if they don't match, they need to be implicitly passed
    """
    called_params = len(called_func.params.params)
    if called_params == 0:
        return call.with_changes(args=[])
    return call


def get_call_from_module(module: str, func: str) -> cst.FunctionDef | None:
    """Open the associated file, and parse the func into a Call.

    The purpose of this is to determine whether we need `implicitly` or not.
    so perform this call as lazily as possible - rather than adding it to
    the migration.
    """
    if not (spec := importlib.util.find_spec(module)):
        logger.warning(f"Failed to find module {module}")
        return None

    assert spec.origin is not None

    with open(spec.origin) as f:
        source_code = f.read()
        tree = cst.parse_module(source_code)
        results = m.findall(tree, matcher=m.FunctionDef(m.Name(func)))
        return cst.ensure_type(results[0], cst.FunctionDef) if results else None
