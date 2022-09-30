# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.openapi.target_types import OpenApiDocumentGeneratorTarget, OpenApiDocumentTarget
from pants.engine.target import BoolField, StringField
from pants.jvm.target_types import PrefixedJvmJdkField, PrefixedJvmResolveField


class OpenApiJavaModelPackageField(StringField):
    alias = "java_model_package"
    help = "Root package for generated model code"


class OpenApiJavaApiPackageField(StringField):
    alias = "java_api_package"
    help = "Root package for generated API code"


class OpenApiJavaSkipField(BoolField):
    alias = "skip_java"
    default = False
    help = "If true, skips generation of Java sources from this target"


def rules():
    return [
        OpenApiDocumentTarget.register_plugin_field(OpenApiJavaSkipField),
        OpenApiDocumentTarget.register_plugin_field(OpenApiJavaModelPackageField),
        OpenApiDocumentTarget.register_plugin_field(OpenApiJavaApiPackageField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(OpenApiJavaSkipField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(OpenApiJavaModelPackageField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(OpenApiJavaApiPackageField),
        # Default Pants JVM fields
        OpenApiDocumentTarget.register_plugin_field(PrefixedJvmJdkField),
        OpenApiDocumentTarget.register_plugin_field(PrefixedJvmResolveField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
    ]
