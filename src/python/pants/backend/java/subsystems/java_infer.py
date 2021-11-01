# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import cast

from pants.option.subsystem import Subsystem
from pants.util.docutil import git_url


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
        _default_package_mapping_url = git_url(
            "src/python/pants/backend/java/dependency_inference/jvm_artifact_mappings.py"
        )
        register(
            "--third-party-import-mapping",
            type=dict,
            help=(
                "A dictionary mapping a Java package path to a JVM artifact coordinate (GROUP:ARTIFACT) "
                "without the version. The package path may be made recursive to match symbols in subpackages "
                "by adding `.**` to the end of the package path. For example, specify `{'org.junit.**': 'junit:junit'} `"
                "to infer a dependency on junit:junit for any file importing a symbol from org.junit or its "
                f"subpackages. Pants also supplies a default package mapping ({_default_package_mapping_url})."
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
