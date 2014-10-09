# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


from pants.backend.jvm.tasks.unpack_external_archive import UnpackExternalArchive
from pants.engine.round_manager import RoundManager
from pants.util.contextutil import temporary_dir

from pants_test.base_test import BaseTest
from pants_test.base.context_utils import create_context


class UnpackExternalArchiveTest(BaseTest):

  def test_simple(self):
    with temporary_dir() as workdir:
      context = create_context()
      unpack_task = UnpackExternalArchive(context, workdir)
      round_manager = RoundManager(context)
      unpack_task.prepare(round_manager)
