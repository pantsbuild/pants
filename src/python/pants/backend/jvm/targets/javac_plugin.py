# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.targets.java_library import JavaLibrary


class JavacPlugin(JavaLibrary):
  """A Java compiler plugin."""

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (Java,)

  def __init__(self, classname=None, plugin=None, *args, **kwargs):

    """
    :param classname: The fully qualified plugin class name - required.
    :param plugin: The name of the plugin. Defaults to name if not supplied.  These are the names
                   passed to javac's -Xplugin flag.
    """
    super().__init__(*args, **kwargs)

    self.plugin = plugin or self.name
    self.classname = classname

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    for spec in super().compute_dependency_specs(kwargs, payload):
      yield spec

    yield Java.global_instance().injectables_spec_for_key('tools.jar')
