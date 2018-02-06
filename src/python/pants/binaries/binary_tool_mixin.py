# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple

from pants.binaries.binary_util import BinaryUtil
from pants.util.memo import memoized_method


class BinaryToolMixin(object):
  """Mixin for classes that use binary executables.

  Must be mixed in to something that can register and use options, e.g., a Task or a Subsystem.
  Specifically, the class this is mixed into must have a get_options() method.

  :API: public
  """
  class BinaryTool(namedtuple('BinaryTool', ['scope', 'supportdir', 'name', 'platform_dependent',
                                             'replaces_scope', 'replaces_name'])):

    # TODO(benjy): Remove replaces_scope/replaces_name after migration to this mixin is complete.
    def select(self, options):
      version = getattr(options.for_scope(self.scope), '{}_version'.format(self.name))
      if self.replaces_scope and self.replaces_name:
        # If the old option is provided explicitly, let it take precedence.
        old_opts = options.for_scope(self.replaces_scope)
        if not old_opts.is_default(self.replaces_name):
          version = old_opts.get(self.replaces_name)
      return BinaryUtil.Factory.create().select(
        self.supportdir, version, self.name, self.platform_dependent)

  @staticmethod
  def get_registered_tools():
    """Returns a map of name to BinaryTool."""
    return BinaryToolMixin._binary_tools

  @staticmethod
  def reset_registered_tools():
    """Needed only for test isolation."""
    BinaryToolMixin._binary_tools = {}

  _binary_tools = {}  # name -> BinaryTool objects.

  @classmethod
  def register_binary_tool(cls,
                           register,
                           supportdir,
                           name,
                           default_version,
                           platform_dependent,
                           fingerprint=True,
                           help=None,
                           removal_version=None,
                           removal_hint=None,
                           # Temporary params, while migrating existing version options.
                           replaces_scope=None,
                           replaces_name=None):
    """Registers a binary tool under `name` for lazy fetching.

    Binaries can be retrieved in `execute` scope via `select_binary`.

    :param register: A function that can register options with the option system.
    :param string supportdir: The dir to find the tool under, as known to BinaryUtil.
    :param string name: The name of the tool, as known to BinaryUtil.
    :param string default_version: The default version of the tool.
    :param bool platform_dependent: Is the binary qualified by platform,
                                    or is it a platform-independent script.
    :param bool fingerprint: Indicates whether to include the tool in the task's fingerprint.
                             Note that unlike for other options, fingerprinting is enabled for
                             tools by default.
    :param unicode help: An optional custom help string; otherwise a reasonable one is generated.
    :param string removal_version: A semver at which this tool will be removed.
    :param string removal_hint: A hint on how to migrate away from this tool.
    :param string replaces_scope: Replaces a previous option in this scope.
    :param string replaces_name: Replaces a previous option of this name in replaces_scope.
    """
    help = help or 'Version of the {} {} to use'.format(
      name, 'binary' if platform_dependent else 'script')
    register('--{}-version'.format(name),
             advanced=True,
             type=str,
             default=default_version,
             help=help,
             fingerprint=fingerprint,
             removal_version=removal_version,
             removal_hint=removal_hint)

    binary_tool = cls.BinaryTool(register.scope, supportdir, name, platform_dependent,
                                 replaces_scope, replaces_name)
    BinaryToolMixin._binary_tools[name] = binary_tool

  @memoized_method
  def select_binary(self, name):
    return self._binary_tools[name].select(self.context.options)