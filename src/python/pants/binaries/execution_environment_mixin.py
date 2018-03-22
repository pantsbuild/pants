# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from abc import abstractmethod

from pants.util.contextutil import environment_as


def prepend_path(prev_env, path_var, new_entries):
  prev_path = prev_env.get(path_var, None)
  if prev_path is None:
    return ':'.join(new_entries)
  return ':'.join(new_entries + prev_path.split(':'))


class ExecutionEnvironmentMixin(object):

  @classmethod
  def apply_successive_env_modifications(cls, env, environment_mixin_instances):
    for env_modifier in environment_mixin_instances:
      env = env_modifier.modify_environment(env)
    return env

  # There's no reason this has to be just about the shell "environment", really
  # just has to be a contextmanager. Implementing this method using a literal
  # chroot, or VM image, or something might be really interesting to just
  # completely sidestep the installation problem.
  @contextmanager
  def execution_environment(self, prev_env=None):
    if prev_env is None:
      prev_env = os.environ
    env_copy = prev_env.copy()
    new_env = self.modify_environment(env_copy)

    with environment_as(**new_env):
      yield

  @abstractmethod
  def modify_environment(self, env): pass


class ExecutionPathEnvironment(ExecutionEnvironmentMixin):

  @abstractmethod
  def get_additional_paths(self): pass

  def modify_environment(self, env):
    additional_paths = self.get_additional_paths()
    new_path = prepend_path(env, 'PATH', additional_paths)
    env['PATH'] = new_path
    return env
