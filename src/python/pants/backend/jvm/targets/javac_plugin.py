# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.java_library import JavaLibrary


class JavacPlugin(JavaLibrary):
  """A Java compiler plugin."""

  def __init__(self, classname=None, plugin=None, *args, **kwargs):

    """
    :param classname: The fully qualified plugin class name - required.
    :param plugin: The name of the plugin. Defaults to name if not supplied.  These are the names
                   passed to javac's -Xplugin flag.
    """

    super(JavacPlugin, self).__init__(*args, **kwargs)

    self.plugin = plugin or self.name
    self.classname = classname
    self.add_labels('javac_plugin')
