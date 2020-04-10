# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.rules.targets import COMMON_JVM_FIELDS
from pants.engine.target import Sources, StringSequenceField, Target


class JaxWsXjcArgs(StringSequenceField):
    """Additional arguments to xjc."""

    alias = "xjc_args"


class JaxWsExtraArgs(StringSequenceField):
    """Additional arguments for the CLI."""

    alias = "extra_args"


class JaxWsLibrary(Target):
    """A Java library generated from JAX-WS wsdl files."""

    alias = "jax_ws_library"
    core_fields = (*COMMON_JVM_FIELDS, Sources, JaxWsXjcArgs, JaxWsExtraArgs)
    v1_only = True
