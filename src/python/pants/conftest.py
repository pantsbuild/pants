# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses

import pytest


@pytest.fixture(autouse=True, scope="session")
def dedicated_target_fields():
    """Ensures we follow our convention of dedicated source and dependencies field per-target.

    This helps ensure that plugin authors can do dependency inference on _specific_ field types, and
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


def _check_frozen_dataclass_attributes() -> None:
    """Ensures that calls to `object.__setattr__` in a frozen dataclass' `__init__` are valid."""

    actual_dataclass_decorator = dataclasses.dataclass

    def new_dataclass_decorator(*args, **kwargs):
        if not kwargs.get("frozen", False):
            return actual_dataclass_decorator(*args, **kwargs)

        def wrapper(cls):
            dataclass_cls = actual_dataclass_decorator(*args, **kwargs)(cls)

            if dataclass_cls.__init__ is cls.__init__:
                old__init__ = getattr(dataclass_cls, "__init__")

                def new__init__(self, *args, **kwargs):
                    old__init__(self, *args, **kwargs)
                    expected = sorted(field.name for field in dataclasses.fields(self))
                    if hasattr(self, "__dict__"):
                        actual = sorted(self.__dict__)
                        assert expected == actual
                    else:
                        for attrname in self.__slots__:
                            # The only way to validate it was initialized is to trigger the descriptor.
                            getattr(self, attrname)

                setattr(dataclass_cls, "__init__", new__init__)

            return dataclass_cls

        return wrapper

    dataclasses.dataclass = new_dataclass_decorator


def pytest_configure() -> None:
    _check_frozen_dataclass_attributes()
