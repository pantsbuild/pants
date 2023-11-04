# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import TypedDict

import yaml

from pants.backend.nfpm.fields.contents import (
    NfpmContentFileGroupField,
    NfpmContentFileModeField,
    NfpmContentFileMtimeField,
    NfpmContentFileOwnerField,
)
from pants.engine.target import Target


class OctalInt(int):
    # noinspection PyUnusedLocal
    @staticmethod
    def represent_octal(dumper: yaml.representer.BaseRepresenter, data: int) -> yaml.Node:
        # YAML 1.2 octal: 0o7777 (py: f"0o{data:o}" or f"{data:#o}" or oct(data))
        # YAML 1.1 octal: 07777 (py: f"0{data:o}")
        # Both octal reprs are supported by `gopkg.in/yaml.v3` which parses YAML in nFPM.
        # See: https://github.com/go-yaml/yaml/tree/v3.0.1#compatibility
        # PyYAML only supports reading YAML 1.1, so we use that.
        return yaml.ScalarNode("tag:yaml.org,2002:int", f"0{data:o}")


# This is an unfortunate import-time side effect: PyYAML does registration globally.
yaml.add_representer(OctalInt, OctalInt.represent_octal)


class NfpmFileInfo(TypedDict, total=False):
    # nFPM allows these to be None or missing.
    # Each of the fields has a default, so in practice, these won't be None.
    owner: str | None
    group: str | None
    mode: OctalInt | None
    mtime: str | None


def file_info(target: Target) -> NfpmFileInfo:
    mode = target[NfpmContentFileModeField].value
    return NfpmFileInfo(
        owner=target[NfpmContentFileOwnerField].value,
        group=target[NfpmContentFileGroupField].value,
        mode=OctalInt(mode) if mode is not None else mode,
        mtime=target[NfpmContentFileMtimeField].value,
    )


class NfpmContent(TypedDict, total=False):
    src: str
    dst: str
    type: str
    packager: str
    file_info: NfpmFileInfo
