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
        OpenApiDocumentTarget.register_plugin_field(OpenApiPythonSkipField),
        OpenApiDocumentTarget.register_plugin_field(OpenApiPythonGeneratorNameField),
        OpenApiDocumentTarget.register_plugin_field(OpenApiPythonAdditionalPropertiesField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(OpenApiPythonSkipField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(
            OpenApiPythonAdditionalPropertiesField
        ),
        OpenApiDocumentGeneratorTarget.register_plugin_field(OpenApiPythonGeneratorNameField),
        # Default Pants python fields
        OpenApiDocumentTarget.register_plugin_field(PrefixedPythonResolveField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(PrefixedPythonResolveField),
    ]
