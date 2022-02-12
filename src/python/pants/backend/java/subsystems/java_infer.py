# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Any

from pants.option.option_types import BoolOption, DictOption
from pants.option.subsystem import Subsystem


class JavaInferSubsystem(Subsystem):
    options_scope = "java-infer"
    help = "Options controlling which dependencies will be inferred for Java targets."

    imports = BoolOption(
        "--imports",
        default=True,
        help=("Infer a target's dependencies by parsing import statements from sources."),
    )
    consumed_types = BoolOption(
        "--consumed-types",
        default=True,
        help=("Infer a target's dependencies by parsing consumed types from sources."),
    )
    third_party_imports = BoolOption(
        "--third-party-imports",
        default=True,
        help="Infer a target's third-party dependencies using Java import statements.",
    )
    # TODO: Move to `coursier` or a generic `jvm` subsystem.
    third_party_import_mapping = DictOption[Any](
        "--third-party-import-mapping",
        help=(
            "A dictionary mapping a Java package path to a JVM artifact coordinate "
            "(GROUP:ARTIFACT) without the version.\n\n"
            "See `jvm_artifact` for more information on the mapping syntax."
        ),
    )
