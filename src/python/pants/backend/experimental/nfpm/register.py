# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Create apk, archlinux, deb, and rpm system packages.

See https://nfpm.goreleaser.com/ for details on nFPM, including these descriptions of it:
  - nFPM is "effing simple package management" 
  - "nFPM is Not FPM--a zero dependencies, simple deb, rpm, apk, and arch linux packager written in Go."
"""  # TODO: include ipk in this docstring once support is added.

from pants.backend.nfpm.dependency_inference import rules as nfpm_dependency_inference_rules
from pants.backend.nfpm.rules import rules as nfpm_rules
from pants.backend.nfpm.subsystem import rules as nfpm_subsystem_rules
from pants.backend.nfpm.target_types import target_types as nfpm_target_types
from pants.backend.nfpm.target_types_rules import rules as nfpm_target_type_rules


def target_types():
    return nfpm_target_types()


def rules():
    return [
        *nfpm_subsystem_rules(),
        *nfpm_target_type_rules(),
        *nfpm_dependency_inference_rules(),
        *nfpm_rules(),
    ]
