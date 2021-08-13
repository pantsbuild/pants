# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from native import impl  # type: ignore[attr-defined]


def get_name():
    return impl.name()
