# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.subsystem.subsystem import Subsystem


class Subprocess(object):
  """A subsystem for managing subprocess state."""

  class Factory(Subsystem):
    # N.B. This scope is completely unused as of now, as this subsystem's current primary function
    # is to surface the `--pants-subprocessdir` global/bootstrap option at runtime. This option
    # needs to be set on the bootstrap scope vs a Subsystem scope such that we have early access
    # to the option (e.g. via `OptionsBootstrapper` vs `OptionsInitializer`) in order to bootstrap
    # process-metadata dependent runs such as the pantsd thin client runner (`RemotePantsRunner`).
    options_scope = 'subprocess'

    def create(self):
      options = self.global_instance().get_options()
      return Subprocess(options.pants_subprocessdir)

  def __init__(self, pants_subprocess_dir):
    self._pants_subprocess_dir = pants_subprocess_dir

  def get_subprocess_dir(self):
    return self._pants_subprocess_dir
