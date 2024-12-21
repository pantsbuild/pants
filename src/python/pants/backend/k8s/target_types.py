# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import ClassVar

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    MultipleSourcesField,
    SingleSourceField,
    SpecialCasedDependencies,
    StringField,
    Target,
    TargetFilesGenerator,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import help_text


class K8sSourceField(SingleSourceField):
    expected_file_extensions: ClassVar[tuple[str, ...]] = (".yml", ".yaml")


class K8sSourcesField(MultipleSourcesField):
    default = ("*.yaml", "*.yml")
    expected_file_extensions: ClassVar[tuple[str, ...]] = (".yml", ".yaml")
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.yaml', 'new_*.yaml', '!old_ignore.yaml']`"
    )


class K8sSourceDependenciesField(Dependencies):
    pass


class K8sSourceTarget(Target):
    alias = "k8s_source"
    core_fields = (
        # Provides `tags`
        *COMMON_TARGET_FIELDS,
        K8sSourceField,
        K8sSourceDependenciesField,
    )
    help = "A single k8s object spec file."


class K8sSourceTargetGenerator(TargetFilesGenerator):
    alias = "k8s_sources"
    generated_target_cls = K8sSourceTarget

    core_fields = (
        # Provides `tags`
        *COMMON_TARGET_FIELDS,
        K8sSourcesField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (K8sSourceDependenciesField,)
    help = help_text(
        f"""
        Generate a `{K8sSourceTarget.alias}` target for each file in the `{K8sSourcesField.alias}` field.
        """
    )


class K8sBundleSourcesField(SpecialCasedDependencies):
    alias = "sources"


class K8sBundleContextField(StringField):
    alias = "context"
    required = True
    help = "The kubectl context to use for deploy."


class K8sBundleDependenciesField(Dependencies):
    alias = "dependencies"


class K8sBundleTarget(Target):
    alias = "k8s_bundle"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        K8sBundleSourcesField,
        K8sBundleContextField,
        K8sBundleDependenciesField,
    )


def target_types():
    return [
        K8sSourceTarget,
        K8sSourceTargetGenerator,
        K8sBundleTarget,
    ]
