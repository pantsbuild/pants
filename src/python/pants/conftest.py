# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import pytest


def pytest_sessionstart(session) -> None:
    pass


def pytest_sessionfinish(session) -> None:
    pass


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
