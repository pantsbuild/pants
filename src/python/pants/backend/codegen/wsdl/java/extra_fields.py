# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.wsdl.target_types import WsdlSourcesGeneratorTarget, WsdlSourceTarget
from pants.engine.target import StringField


class PackageField(StringField):
    alias = "package"
    help = "Override destination package for generated sources"


class ModuleField(StringField):
    alias = "module"
    help = "Java module name"


def rules():
    return [
        WsdlSourceTarget.register_plugin_field(PackageField),
        WsdlSourcesGeneratorTarget.register_plugin_field(PackageField),
        WsdlSourceTarget.register_plugin_field(ModuleField),
        WsdlSourcesGeneratorTarget.register_plugin_field(ModuleField),
    ]
