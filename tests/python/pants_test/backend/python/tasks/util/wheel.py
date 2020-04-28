# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sysconfig
from os import PathLike
from typing import Tuple, Union


def _normalize_platform_tag(platform_tag: str) -> str:
    return platform_tag.replace("-", "_").replace(".", "_")


def name_and_platform(whl: Union[str, PathLike]) -> Tuple[str, str, str]:
    # The wheel filename is of the format
    # {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
    # See https://www.python.org/dev/peps/pep-0425/.
    # We don't care about the python or abi versions (they depend on what we're currently
    # running on), we just want to make sure we have all the platforms we expect.
    parts = os.path.splitext(os.fspath(whl))[0].split("-")
    dist = parts[0]
    version = parts[1]
    platform_tag = parts[-1]
    return dist, version, _normalize_platform_tag(platform_tag)


def normalized_current_platform() -> str:
    return _normalize_platform_tag(sysconfig.get_platform())
