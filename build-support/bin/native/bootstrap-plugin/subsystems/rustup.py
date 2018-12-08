# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from contextlib import contextmanager

from pants.base.build_environment import get_buildroot, get_pants_cachedir
from pants.binaries.binary_tool import Script
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.rules import rule
from pants.net.http.fetcher import Fetcher
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import environment_as
from pants.util.dirutil import chmod_plus_x, is_executable
from pants.util.memo import memoized_property
from pants.util.objects import datatype
from pants.util.process_handler import subprocess


class RustupUrlGenerator(BinaryToolUrlGenerator):

  RUSTUP_SCRIPT_URL = 'https://sh.rustup.rs'

  def generate_urls(self, version, host_platform):
    return [self.RUSTUP_SCRIPT_URL]


class Rustup(Script):
  options_scope = 'rustup'

  def get_external_url_generator(self):
    return RustupUrlGenerator()


class RustupToolchain(Subsystem):

  @memoized_property
  def _toolchain_root(self):
    return os.path.join(get_pants_cachedir(), 'rust')

  @memoized_property
  def _cargo_home(self):
    return os.path.join(self._toolchain_root, 'cargo')

  @memoized_property
  def _rustup_home(self):
    return os.path.join(self._toolchain_root, 'rustup')

  @contextmanager
  def _rustup_env(self):
    with environment_as(CARGO_HOME=self._cargo_home,
                        RUSTUP_HOME=self._rustup_home):
      yield
