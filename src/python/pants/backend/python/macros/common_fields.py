# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ClassVar, Dict, Iterable, Tuple

from pants.backend.python.target_types import (
    PythonRequirementModulesField,
    PythonRequirementTarget,
    PythonRequirementTypeStubModulesField,
    normalize_module_mapping,
)
from pants.engine.addresses import Address
from pants.engine.target import DictStringToStringSequenceField, OverridesField
from pants.util.frozendict import FrozenDict
from pants.util.strutil import help_text


class ModuleMappingField(DictStringToStringSequenceField):
    alias = "module_mapping"
    help = help_text(
        f"""
        A mapping of requirement names to a list of the modules they provide.

        For example, `{{"ansicolors": ["colors"]}}`.

        Any unspecified requirements will use a default. See the
        `{PythonRequirementModulesField.alias}` field from the `{PythonRequirementTarget.alias}`
        target for more information.
        """
    )
    value: FrozenDict[str, tuple[str, ...]]
    default: ClassVar[FrozenDict[str, tuple[str, ...]]] = FrozenDict()

    @classmethod
    def compute_value(  # type: ignore[override]
        cls, raw_value: Dict[str, Iterable[str]], address: Address
    ) -> FrozenDict[str, Tuple[str, ...]]:
        value_or_default = super().compute_value(raw_value, address)
        return normalize_module_mapping(value_or_default)


class TypeStubsModuleMappingField(DictStringToStringSequenceField):
    alias = "type_stubs_module_mapping"
    help = help_text(
        f"""
        A mapping of type-stub requirement names to a list of the modules they provide.

        For example, `{{"types-requests": ["requests"]}}`.

        If the requirement is not specified _and_ its name looks like a type stub, Pants will
        use a default. See the `{PythonRequirementTypeStubModulesField.alias}` field from the
        `{PythonRequirementTarget.alias}` target for more information.
        """
    )
    value: FrozenDict[str, tuple[str, ...]]
    default: ClassVar[FrozenDict[str, tuple[str, ...]]] = FrozenDict()

    @classmethod
    def compute_value(  # type: ignore[override]
        cls, raw_value: Dict[str, Iterable[str]], address: Address
    ) -> FrozenDict[str, Tuple[str, ...]]:
        value_or_default = super().compute_value(raw_value, address)
        return normalize_module_mapping(value_or_default)


class RequirementsOverrideField(OverridesField):
    help = help_text(
        """
        Override the field values for generated `python_requirement` targets.

        Expects a dictionary of requirements to a dictionary for the
        overrides. You may either use a string for a single requirement,
        or a string tuple for multiple requirements. Each override is a dictionary of
        field names to the overridden value.

        For example:

            ```
            overrides={
                "django": {"dependencies": ["#setuptools"]]},
                "ansicolors": {"description": "pretty colors"]},
                ("ansicolors, "django"): {"tags": ["overridden"]},
            }
            ```

        Every overridden requirement is validated to be generated by this target.

        You can specify the same requirement in multiple keys, so long as you don't
        override the same field more than one time for the requirement.
        """
    )
