# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from six import string_types

from pants.contrib.node.targets.node_package import NodePackage


logger = logging.getLogger(__name__)


class NodeModule(NodePackage):
  """A Node module."""

  def __init__(
    self, package_manager=None, sources=None, build_script=None, output_dir='dist',
    dev_dependency=False, style_ignore_path='.eslintignore', address=None, payload=None,
    bin_executables=None, node_scope=None, **kwargs):
    """
    :param sources: Javascript and other source code files that make up this module; paths are
                    relative to the BUILD file's directory.
    :type sources: `globs`, `rglobs` or a list of strings

    :param package_manager: choose among supported package managers (npm or yarn).
    :param build_script: build script name as defined in package.json.  All files that are needed
      for the build script must be included in sources.  The script should output build results
      in the directory specified by output_dir.  If build_script is not supplied, the node
      installation results will be considered as output. The output can be archived or included as
      resources for JVM target.
    :param output_dir: relative path to assets generated by build script. The path will be
      preserved in the created JAR if the target is used as a JVM target dependency.
    :param dev_dependency: boolean value.  Default is False. If a node_module is used as parts
      of devDependencies and thus should not be included in the final bundle or JVM binaries, set
      this value to True.
    :param style_ignore_path: relative path to file specifying patterns of files to ignore. The syntax
      supported is the same as the .eslintignore/.gitignore syntax.
    :param bin_executables: A map of executable names to local file name. If a single executable is
                            specified (a string), the package name will be the executable name
                            and the value will be the local file name per package.json rules.
    :type bin_executables: `dict`, where key is bin name and value is a local file path to an executable
                           E.G. { 'app': './cli.js', 'runner': './scripts/run.sh' }
                           `string`, file path and package name as  the default bin name
                           E.G. './cli.js' would be interpreted as { 'app': './cli.js' }
    :param node_scope: Groups related packages together by adding a scope. The `@`
      symbol is typically used for specifying scope in the package name in `package.json`.
      However pants target addresses do not allow for `@` in the target address.
      A repo-level default scope can be added with the --node-distribution-node-scope option.
      Any target-level node_scope will override the global node-scope.

    """
    # TODO(John Sirois): Support devDependencies, etc.  The devDependencies case is not
    # clear-cut since pants controlled builds would provide devDependencies as needed to perform
    # tasks.  The reality is likely to be though that both pants will never cover all cases, and a
    # back door to execute new tools during development will be desirable and supporting conversion
    # of pre-existing package.json files as node_module targets will require this.

    bin_executables = bin_executables or {}
    if not (isinstance(bin_executables, dict) or isinstance(bin_executables, string_types)):
      raise TargetDefinitionException(
        self,
        'expected a `dict` or `str` object for bin_executables, instead found a {}'
        .format(type(bin_executables)))

    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(
        sources=sources, sources_rel_path=address.spec_path, key_arg='sources'),
      'build_script': PrimitiveField(build_script),
      'package_manager': PrimitiveField(package_manager),
      'output_dir': PrimitiveField(output_dir),
      'dev_dependency': PrimitiveField(dev_dependency),
      'style_ignore_path': PrimitiveField(style_ignore_path),
      'bin_executables': PrimitiveField(bin_executables),
      'node_scope': PrimitiveField(node_scope),
    })
    super(NodeModule, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def style_ignore_path(self):
    """The name of the ignore path file.

    :rtype: string
    """
    return self.payload.style_ignore_path

  @property
  def bin_executables(self):
    """A normalized map of bin executable names and local path to an executable

    :rtype: dict
    """
    if isinstance(self.payload.bin_executables, string_types):
      # In this case, the package_name is the bin name
      return { self.package_name: self.payload.bin_executables }

    return self.payload.bin_executables
