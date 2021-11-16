# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import cast

from pants.option.subsystem import Subsystem


class JavaInferSubsystem(Subsystem):
    options_scope = "java-infer"
    help = "Options controlling which dependencies will be inferred for Java targets."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--imports",
            default=True,
            type=bool,
            help=("Infer a target's dependencies by parsing import statements from sources."),
        )
        register(
            "--consumed-types",
            default=True,
            type=bool,
            help=("Infer a target's dependencies by parsing consumed types from sources."),
        )
        register(
            "--third-party-imports",
            default=True,
            type=bool,
            help="Infer a target's third-party dependencies using Java import statements.",
        )
        # TODO: Move to `coursier` or a generic `jvm` subsystem.
        register(
            "--third-party-import-mapping",
            type=dict,
            help=(
                "A dictionary mapping a Java package path to a JVM artifact coordinate "
                "(GROUP:ARTIFACT) without the version.\n\n"
                "See `jvm_artifact` for more information on the mapping syntax."
            ),
        )

    @property
    def imports(self) -> bool:
        return cast(bool, self.options.imports)

    @property
    def consumed_types(self) -> bool:
        return cast(bool, self.options.consumed_types)

    @property
    def third_party_imports(self) -> bool:
        return cast(bool, self.options.third_party_imports)

    @property
    def third_party_import_mapping(self) -> dict:
        return cast(dict, self.options.third_party_import_mapping)
