# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import StrOption
from pants.option.subsystem import Subsystem


class SemanticDbSubsystem(Subsystem):
    options_scope = "scalac-semanticdb"
    help = "semanticdb (ttps://scalameta.org/docs/semanticdb/)"

    version = StrOption(default="4.8.10", help="The version for SemanticDB Scalac plugin")
