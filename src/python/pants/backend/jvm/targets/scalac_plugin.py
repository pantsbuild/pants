# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.scala_library import ScalaLibrary


class ScalacPlugin(ScalaLibrary):
  """A Scala compiler plugin."""

  @classmethod
  def subsystem_dependencies(cls):
    return super(ScalacPlugin, cls).subsystem_dependencies() + (ScalaPlatform,)

  def __init__(self, classname=None, plugin=None, *args, **kwargs):
    """
    :param classname: The fully qualified plugin class name - required.
    :param plugin: The name of the plugin. Defaults to name if not supplied.
    """

    super(ScalacPlugin, self).__init__(*args, **kwargs)

    self.plugin = plugin or self.name
    self.classname = classname
    self.add_labels('scalac_plugin')

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    for spec in super(ScalacPlugin, cls).compute_dependency_specs(kwargs, payload):
      yield spec

    for spec in ScalaPlatform.global_instance().injectables_specs_for_key('scalac'):
      yield spec
