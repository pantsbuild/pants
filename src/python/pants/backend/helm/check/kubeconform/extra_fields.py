# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass

from pants.engine.target import BoolField, FieldSet, Target
from pants.util.docutil import bin_name
from pants.util.strutil import softwrap


class KubeconformSkipField(BoolField):
    alias = "skip_kubeconform"
    default = False
    help = softwrap(
        f"""
        If set to true, do not run any kubeconform checking in this Helm target when running
        `{bin_name()} check`.
        """
    )


@dataclass(frozen=True)
class KubeconformFieldSet(FieldSet, metaclass=ABCMeta):
    skip: KubeconformSkipField

    @classmethod
    def opt_out(cls, target: Target) -> bool:
        return target[KubeconformSkipField].value
