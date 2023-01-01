# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from native import impl  # type: ignore[attr-defined]  # pants: no-infer-dep


def get_name():
    return impl.name()
