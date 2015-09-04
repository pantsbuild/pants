# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple

from pants.pantsd.service.fs_event_service import FSEventService


class TestExecutor(object):
  FakeFuture = namedtuple('FakeFuture', ['done', 'result'])

  def submit(self, closure, *args, **kwargs):
    result = closure(*args, **kwargs)
    return self.FakeFuture(lambda: True, lambda: result)


class LumberJack:
  BUILD_ROOT = '/Users/sserebryakov/workspace/source'

  def run(self):
    self.service = FSEventService(self.BUILD_ROOT, TestExecutor())
    self.service.register_simple_handler('BUILD', lambda x: print(x))
    self.service.run()


if __name__ == '__main__':
  LumberJack().run()
