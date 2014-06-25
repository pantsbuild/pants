# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.console_task import ConsoleTask


class PathDeps(ConsoleTask):
  def console_output(self, targets):
    return set(t.address.build_file.parent_path for t in targets if hasattr(t, 'address'))
