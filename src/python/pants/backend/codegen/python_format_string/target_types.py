# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging

from pants.core.goals.package import OutputPathField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    DictStringToStringField,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
)

logger = logging.getLogger(__name__)


class PythonFormatStringSourceField(SingleSourceField):
    pass


class PythonFormatStringValuesField(DictStringToStringField):
    alias = "values"
    required = True


class PythonFormatStringOutputPathField(OutputPathField):
    def value_or_default(self, *, file_ending: str | None) -> str:
        if self.address.is_generated_target:
            if self.address.is_parametrized:
                return f"{self.address.filename}.{file_ending}{self.address.parameters_repr}"
            return f"{self.address.filename}.{file_ending}"
        return super().value_or_default(file_ending=file_ending)


class PythonFormatStringTarget(Target):
    alias = "python_format_string"
    help = "Substitutes values into a file. See k8s backend documentation for details."
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonFormatStringSourceField,
        PythonFormatStringValuesField,
        PythonFormatStringOutputPathField,
    )


class PythonFormatStringsSourcesField(MultipleSourcesField):
    pass


class PythonFormatStringTargetGenerator(TargetFilesGenerator):
    alias = "python_format_strings"
    generated_target_cls = PythonFormatStringTarget
    help = "Substitutes values into files. See k8s backend documentation for details."
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonFormatStringsSourcesField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (PythonFormatStringValuesField,)


def target_types():
    return (
        PythonFormatStringTarget,
        PythonFormatStringTargetGenerator,
    )
