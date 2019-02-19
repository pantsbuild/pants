# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.contrib.rust.targets.cargo_base_library import CargoBaseLibrary


class CargoSyntheticLibrary(CargoBaseLibrary):
  """A base class for all cargo targets."""
