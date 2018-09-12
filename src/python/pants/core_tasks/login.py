# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.auth.basic_auth import BasicAuth
from pants.base.exceptions import TaskError
from pants.task.task import Task


class Login(Task):
  """Task to auth against some identity provider.

  :API: public
  """

  @classmethod
  def subsystem_dependencies(cls):
    return super(Login, cls).subsystem_dependencies() + (BasicAuth,)

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def register_options(cls, register):
    super(Login, cls).register_options(register)
    register('--to', fingerprint=True,
             help='Log in to this provider.  Can also be specified as a passthru arg.')


  def execute(self):
    # TODO: When we have other auth methods (e.g., OAuth2), select one by provider name.
    requested_providers = list(filter(None, [self.get_options().to] + self.get_passthru_args()))
    if len(requested_providers) != 1:
      raise TaskError('Must specify exactly one provider.')
    BasicAuth.global_instance().authenticate(requested_providers[0])
