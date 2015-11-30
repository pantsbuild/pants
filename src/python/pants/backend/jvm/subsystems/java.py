# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.zinc_language_mixin import ZincLanguageMixin
from pants.subsystem.subsystem import Subsystem


class Java(ZincLanguageMixin, Subsystem):
  """A subsystem to encapsulate Java language features.

  Platform specific options (ie, JDK specific) are captured by the JvmPlatform subsystem.
  """
  options_scope = 'java'
