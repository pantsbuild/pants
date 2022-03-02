# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.soap.java import rules as wsdl_java
from pants.backend.codegen.soap.rules import rules as wsdl_rules
from pants.backend.codegen.soap.target_types import WsdlSourcesGeneratorTarget, WsdlSourceTarget


def target_types():
    return [WsdlSourceTarget, WsdlSourcesGeneratorTarget]


def rules():
    return [
        *wsdl_rules(),
        *wsdl_java.rules(),
    ]
