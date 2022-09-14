# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.openapi.target_types import OpenApiSourceGeneratorTarget, OpenApiSourceTarget
from pants.engine.target import BoolField, StringField
from pants.jvm.target_types import PrefixedJvmJdkField, PrefixedJvmResolveField


class OpenApiJavaModelPackageField(StringField):
    alias = "java_model_package"
    help = "Root package for generated model code"


class OpenApiJavaApiPackageField(StringField):
    alias = "java_api_package"
    help = "Root package for generated API code"


class OpenApiJavaCodegenSkipField(BoolField):
    alias = "skip_java"
    default = False
    help = "If true, skips generation of Java sources from this target"


def rules():
    return [
        OpenApiSourceTarget.register_plugin_field(OpenApiJavaCodegenSkipField),
        OpenApiSourceTarget.register_plugin_field(OpenApiJavaModelPackageField),
        OpenApiSourceTarget.register_plugin_field(OpenApiJavaApiPackageField),
        OpenApiSourceGeneratorTarget.register_plugin_field(OpenApiJavaCodegenSkipField),
        OpenApiSourceGeneratorTarget.register_plugin_field(OpenApiJavaModelPackageField),
        OpenApiSourceGeneratorTarget.register_plugin_field(OpenApiJavaApiPackageField),
        # Default Pants JVM fields
        OpenApiSourceTarget.register_plugin_field(PrefixedJvmJdkField),
        OpenApiSourceTarget.register_plugin_field(PrefixedJvmResolveField),
        OpenApiSourceGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        OpenApiSourceGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
    ]
