# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.soap.target_types import WsdlSourcesGeneratorTarget, WsdlSourceTarget
from pants.engine.target import StringField


class JavaPackageField(StringField):
    alias = "package"
    help = "Override destination package for generated sources"


class JavaModuleField(StringField):
    alias = "module"
    help = "Java module name"


def rules():
    return [
        WsdlSourceTarget.register_plugin_field(JavaPackageField),
        WsdlSourcesGeneratorTarget.register_plugin_field(JavaPackageField),
        WsdlSourceTarget.register_plugin_field(JavaModuleField),
        WsdlSourcesGeneratorTarget.register_plugin_field(JavaModuleField),
    ]
