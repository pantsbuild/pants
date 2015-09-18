# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.task import Task


class TestTaskMixin(Task):
    @classmethod
    def register_options(cls, register):
        register('--disable-test-timeout', action='store_true', default=False,
             help='Disable test timeouts')
        register('--default-test-timeout', action='store', default=0, type=int,
                 help='The default timeout for a test if timeout is not set in BUILD')

    def timeout(self, timeout):
        if self.get_options().disable_test_timeout:
            return None
        else:
            if timeout is None:
                return self.get_options().default_test_timeout
            else:
                return timeout
