# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.contrib.rust.targets.cargo_base_custom_build import CargoBaseCustomBuild


class CargoSyntheticCustomBuild(CargoBaseCustomBuild):
  """A base class for all cargo targets."""
