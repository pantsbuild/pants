# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from mock import Mock
import pytest

from pants.backend.jvm.tasks.jar_publish import JarPublish
from pants.base.exceptions import TaskError
from pants.util.contextutil import temporary_dir
from pants_test.base_test import BaseTest
from pants_test.tasks.test_base import prepare_task


class JarPublishTest(BaseTest):

  def test_smoke_publish(self):
    with temporary_dir() as publish_dir:
      task = prepare_task(JarPublish,
                        args=['--test-local=%s' % publish_dir],
                        build_graph=self.build_graph,
                        build_file_parser=self.build_file_parser)
      task.scm = Mock()
      task.execute()

  def test_publish_local_only(self):
    with pytest.raises(TaskError) as exc:
      prepare_task(JarPublish)
