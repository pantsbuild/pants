# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.engine.rules import optionable_rule, rule
from pants.subsystem.subsystem import Subsystem
from pants.util.objects import datatype, string_optional


class SubprocessEncodingEnvironment(datatype([
    ('lang', string_optional),
    ('lc_all', string_optional),
])):

  @property
  def invocation_environment_dict(self):
    return {
      'LANG': self.lang or '',
      'LC_ALL': self.lc_all or '',
    }


class SubprocessEnvironment(Subsystem):
  options_scope = 'subprocess-environment'

  @classmethod
  def register_options(cls, register):
    super(SubprocessEnvironment, cls).register_options(register)

    # TODO(#7735): move this to general subprocess support!
    register('--lang',
             default=os.environ.get('LANG'),
             fingerprint=True, advanced=True,
             help='Override the `LANG` environment variable for any forked subprocesses.')
    register('--lc-all',
             default=os.environ.get('LC_ALL'),
             fingerprint=True, advanced=True,
             help='Override the `LC_ALL` environment variable for any forked subprocesses.')


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
