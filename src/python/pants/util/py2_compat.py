# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from future.utils import PY3


if PY3:
  import configparser  # noqa: F401
else:
  from backports import configparser  # noqa: F401
