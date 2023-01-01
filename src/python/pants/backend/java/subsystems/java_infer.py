# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Any

from pants.option.option_types import BoolOption, DictOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class JavaInferSubsystem(Subsystem):
    options_scope = "java-infer"
    help = "Options controlling which dependencies will be inferred for Java targets."

    imports = BoolOption(
        default=True,
        help="Infer a target's dependencies by parsing import statements from sources.",
    )
    consumed_types = BoolOption(
        default=True,
        help="Infer a target's dependencies by parsing consumed types from sources.",
    )
    # TODO: Move to `coursier` or a generic `jvm` subsystem.
    third_party_import_mapping = DictOption[Any](
        help=softwrap(
            """
            A dictionary mapping a Java package path to a JVM artifact coordinate
            (GROUP:ARTIFACT) without the version.

            See `jvm_artifact` for more information on the mapping syntax.
            """
        ),
    )
