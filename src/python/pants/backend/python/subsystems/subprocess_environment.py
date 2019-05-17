# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
from textwrap import dedent

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems import pex_build_util
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.base.exceptions import IncompatiblePlatformsError
from pants.binaries.executable_pex_tool import ExecutablePexTool
from pants.engine.rules import rule, optionable_rule
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf, datatype, string_optional
from pants.util.strutil import safe_shlex_join, safe_shlex_split


logger = logging.getLogger(__name__)


class SubprocessEncodingEnvironment(datatype([
    ('lang', string_optional),
    ('lc_all', string_optional),
])):
  """???"""

  @property
  def invocation_environment_dict(self):
    return {
      'LANG': self.lang or '',
      'LC_ALL': self.lc_all or '',
    }


class SubprocessEnvironment(Subsystem):
  """???"""
  options_scope = 'subprocess-environment'

  @classmethod
  def register_options(cls, register):
    super(SubprocessEnvironment, cls).register_options(register)

    # TODO(#7735): move this to general subprocess support!
    register('--lang',
             default=os.environ.get('LANG'),
             fingerprint=True, advanced=True,
             help='???')
    register('--lc-all',
             default=os.environ.get('LC_ALL'),
             fingerprint=True, advanced=True,
             help='???')


@rule(SubprocessEncodingEnvironment, [SubprocessEnvironment])
def create_subprocess_encoding_environment(subprocess_environment):
  return SubprocessEncodingEnvironment(
    lang=subprocess_environment.get_options().lang,
    lc_all=subprocess_environment.get_options().lc_all,
  )


def rules():
  return [
    optionable_rule(SubprocessEnvironment),
    create_subprocess_encoding_environment,
  ]
