# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass
from typing import Type

from pants.backend.helm.target_types import HelmChartTarget, HelmDeploymentTarget
from pants.engine.target import (
    BoolField,
    Field,
    FieldSet,
    StringField,
    StringSequenceField,
    Target,
    TriBoolField,
)
from pants.util.docutil import bin_name
from pants.util.strutil import help_text


class KubeconformSkipField(BoolField):
    alias = "skip_kubeconform"
    default = False
    help = help_text(
        f"""
        If set to true, do not run any kubeconform checking in this Helm target when running
        `{bin_name()} check`.
        """
    )


class KubeconformIgnoreSourcesField(StringSequenceField):
    alias = "kubeconform_ignore_sources"
    help = help_text("""Regular expression patterns specifying paths to ignore.""")


class KubeconformIgnoreMissingSchemasField(TriBoolField):
    alias = "kubeconform_ignore_missing_schemas"
    help = help_text("""Whether to fail if there are missing schemas for custom resources.""")


class KubeconformStrictField(TriBoolField):
    alias = "kubeconform_strict"
    help = help_text("Run Kubeconform in strict mode.")


class KubeconformSkipKindsField(StringSequenceField):
    alias = "kubeconform_skip_kinds"
    help = help_text("List of kinds or GVKs to ignore.")


class KubeconformRejectKindsField(StringSequenceField):
    alias = "kubeconform_reject_kinds"
    help = help_text("List of kinds or GVKs to reject.")


class KubeconformKubernetesVersionField(StringField):
    alias = "kubeconform_kubernetes_version"
    help = help_text("Kubernetes version to use for the validation.")


@dataclass(frozen=True)
class KubeconformFieldSet(FieldSet, metaclass=ABCMeta):
    skip: KubeconformSkipField
    ignore_sources: KubeconformIgnoreSourcesField
    ignore_missing_schemas: KubeconformIgnoreMissingSchemasField
    strict: KubeconformStrictField
    reject_kinds: KubeconformRejectKindsField
    skip_kinds: KubeconformSkipKindsField
    kubernetes_version: KubeconformKubernetesVersionField

    @classmethod
    def opt_out(cls, target: Target) -> bool:
        return target[KubeconformSkipField].value


_HELM_TARGET_TYPES: list[Type[Target]] = [HelmChartTarget, HelmDeploymentTarget]
_KUBECONFORM_COMMON_FIELD_TYPES: list[Type[Field]] = [
    KubeconformSkipField,
    KubeconformIgnoreSourcesField,
    KubeconformIgnoreMissingSchemasField,
    KubeconformSkipKindsField,
    KubeconformRejectKindsField,
    KubeconformStrictField,
    KubeconformKubernetesVersionField,
]


def rules():
    return [
        tgt.register_plugin_field(field)
        for tgt in _HELM_TARGET_TYPES
        for field in _KUBECONFORM_COMMON_FIELD_TYPES
    ]
