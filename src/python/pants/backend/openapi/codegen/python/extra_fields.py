from pants.backend.openapi.target_types import OpenApiDocumentGeneratorTarget, OpenApiDocumentTarget
from pants.engine.target import BoolField, StringField
from pants.jvm.target_types import PrefixedJvmJdkField, PrefixedJvmResolveField


class OpenApiPythonModelPackageField(StringField):
    alias = "python_model_package"
    help = "Root package for generated model code"


class OpenApiPythonApiPackageField(StringField):
    alias = "python_api_package"
    help = "Root package for generated API code"


class OpenApiPythonSkipField(BoolField):
    alias = "skip_python"
    default = False
    help = "If true, skips generation of Python sources from this target"


def rules():
    return [
        OpenApiDocumentTarget.register_plugin_field(OpenApiPythonSkipField),
        OpenApiDocumentTarget.register_plugin_field(OpenApiPythonModelPackageField),
        OpenApiDocumentTarget.register_plugin_field(OpenApiPythonApiPackageField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(OpenApiPythonSkipField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(OpenApiPythonModelPackageField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(OpenApiPythonApiPackageField),
        # Default Pants JVM fields
        # OpenApiDocumentTarget.register_plugin_field(PrefixedJvmJdkField),
        # OpenApiDocumentTarget.register_plugin_field(PrefixedJvmResolveField),
        # OpenApiDocumentGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        # OpenApiDocumentGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
    ]
