# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.targets.scala_library import ScalaLibrary


class ScalacPlugin(ScalaLibrary):
  """Defines a target that produces a scalac_plugin."""

  def __init__(self, classname=None, plugin=None, *args, **kwargs):

    """
    :param name: The name of this module target, addressable via pants via the portion of the
      spec following the colon - required.
    :param classname: The fully qualified plugin class name - required.
    :param plugin: The name of the plugin which defaults to name if not supplied.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param java_sources: Java libraries this library has a *circular*
      dependency on.
      Prefer using ``dependencies`` to express non-circular dependencies.
    :type java_sources: target spec or list of target specs
    :param provides: The ``artifact``
      to publish that represents this target outside the repo.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param resources: An optional list of paths (DEPRECATED) or ``resources``
      targets containing resources that belong on this library's classpath.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """

    super(ScalacPlugin, self).__init__(*args, **kwargs)

    self.plugin = plugin or self.name
    self.classname = classname
    self.add_labels('scalac_plugin')
