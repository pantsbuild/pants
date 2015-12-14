# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated_module
from pants.task.scm_publish_mixin import Namedver, ScmPublishMixin, Semver, Version


deprecated_module('0.0.66',
                  hint_message='pants.backend.core.tasks.scm_publish has moved to '
                               'pants.task.scm_publish_mixin. Replace deps on '
                               'src/python/pants/backend/core/tasks:scm_publish and on '
                               'src/python/pants/backend/core/tasks:all with a dep on '
                               'src/python/pants/task and change imports accordingly.')

Version = Version
Namedver = Namedver
Semver = Semver
ScmPublishMixin = ScmPublishMixin
