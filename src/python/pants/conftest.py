# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import pytest

# The top-level `pants` module must be a namespace package, because we build two dists from it
# (pantsbuild.pants, and pantsbuild.pants.testutil) and consumers of these dists need to be
# able to import from both.
#
# In fact it is an *implicit* namespace package - that is, it has no __init__.py file.
# See https://packaging.python.org/guides/packaging-namespace-packages/ .
#
# Unfortunately, the presence or absence of __init__.py affects how pytest determines the
# module names for test code. For details see
# https://docs.pytest.org/en/stable/goodpractices.html#test-package-name .
#
# Usually this doesn't matter, as tests don't typically care about their own module name.
# But we have tests (notably those in src/python/pants/engine) that create @rules and
# expect them to have certain names. And @rule names are generated from the name of the module
# containing the rule function...
#
# To allow those tests to work naturally (with expected module names relative to `src/python`)
# we artificially create `src/python/pants/__init__.py` in the test sandbox, to force
# pytest to determine module names relative to `src/python` (instead of `src/python/pants`).
#
# Note that while this makes the (implicit) namespace package into a regular package,
# that is fine at test time. We don't consume testutil from a dist but from source, in the same
# source root (src/python). We only need `pants` to be a namespace package in the dists we create.
namespace_init_path = Path("src/python/pants/__init__.py")


def pytest_sessionstart(session) -> None:
    if namespace_init_path.exists():
        raise Exception(
            f"In order for `pants` to be a namespace package, {namespace_init_path} must not "
            f"exist on disk. See the explanation in {__file__}."
        )
    namespace_init_path.touch()


def pytest_sessionfinish(session) -> None:
    # Technically unecessary, but nice if people are running tests directly from repo
    # (not using pants).
    namespace_init_path.unlink()


@pytest.fixture(autouse=True, scope="session")
def dedicated_target_fields():
    """Ensures we follow our convention of dedicated source and dependencies field per-target.

    This help ensure that plugin authors can do dependency inference on _specific_ field types, and
    not have to filter targets using generic field types.

    Note that this can't help us if a target type should use an _even more specialized_ dependencies
    field type (E.g. 100 different target subclasses could use 1 custom dependencies field type,
    when in reality there should be many more). However, this is a good sanity check.
    """
    from pants.engine.target import Dependencies, SourcesField, Target

    for cls in Target.__subclasses__():
        if hasattr(cls, "core_fields"):
            for field_cls in cls.core_fields:
                # NB: We want to check for all kinds of SourcesFields, like SingleSourceField and
                # MultipleSourcesField.
                if (
                    issubclass(field_cls, SourcesField)
                    and field_cls.__module__ is SourcesField.__module__
                ):
                    raise ValueError(
                        f"{cls.__name__} should have a dedicated field type for the source(s) field."
                    )
                if (
                    issubclass(field_cls, Dependencies)
                    and field_cls.__module__ is Dependencies.__module__
                ):
                    raise ValueError(
                        f"{cls.__name__} should have a dedicated field type for the dependencies field."
                    )
