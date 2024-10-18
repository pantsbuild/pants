# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import itertools
from pants.backend.openapi.target_types import OpenApiDocumentGeneratorTarget, OpenApiDocumentTarget
from pants.backend.python.target_types import PrefixedPythonResolveField
from pants.engine.target import BoolField, DictStringToStringField, StringField


class OpenApiPythonGeneratorNameField(StringField):
    alias = "python_generator_name"
    required = False
    help = "Python generator name"


class OpenApiPythonAdditionalPropertiesField(DictStringToStringField):
    alias = "python_additional_properties"
    help = "Additional properties for python generator"


class OpenApiPythonSkipField(BoolField):
    alias = "skip_python"
    default = False
    help = "If true, skips generation of Python sources from this target"


def rules():
    return [
        target.register_plugin_field(field)
        for target, field in itertools.product(
            (
                OpenApiDocumentTarget,
                OpenApiDocumentGeneratorTarget,
            ),
            (
                OpenApiPythonSkipField,
                OpenApiPythonGeneratorNameField,
                OpenApiPythonAdditionalPropertiesField,
                PrefixedPythonResolveField,
            ),
        )
    ]
