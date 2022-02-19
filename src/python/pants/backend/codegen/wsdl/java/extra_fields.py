# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import StringField

from pants.backend.codegen.wsdl.target_types import WsdlSourcesGeneratorTarget, WsdlSourceTarget


class PackageField(StringField):
    alias = "package"
    help = "Override destination package for generated sources"


def rules():
    return [
        WsdlSourceTarget.register_plugin_field(PackageField),
        WsdlSourcesGeneratorTarget.register_plugin_field(PackageField),
    ]
