# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os


class InterpreterCacheTestMixin(object):
  """A mixin to allow tests to use the "real" interpreter cache.

  This is so each test doesn't waste huge amounts of time recreating the cache on each run.

  Note: Must be mixed in to a subclass of BaseTest.
  """

  def setUp(self):
    super(InterpreterCacheTestMixin, self).setUp()

    # It would be nice to get the location of the real interpreter cache from PythonSetup,
    # but unfortunately real subsystems aren't available here (for example, we have no access
    # to the enclosing pants instance's options), so we have to hard-code it.
    python_setup_workdir = os.path.join(self.real_build_root, '.pants.d', 'python-setup')
    self.set_options_for_scope('python-setup',
        interpreter_cache_dir=os.path.join(python_setup_workdir, 'interpreters'),
        chroot_cache_dir=os.path.join(python_setup_workdir, 'chroots'))
