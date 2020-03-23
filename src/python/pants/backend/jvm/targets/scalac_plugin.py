# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.scala_library import ScalaLibrary


class ScalacPlugin(ScalaLibrary):
    """A Scala compiler plugin."""

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (ScalaPlatform,)

    def __init__(self, classname=None, plugin=None, *args, **kwargs):
        """
        :param classname: The fully qualified plugin class name - required.
        :param plugin: The name of the plugin. Defaults to name if not supplied.
        """

        super().__init__(*args, **kwargs)

        self.plugin = plugin or self.name
        self.classname = classname

    @classmethod
    def compute_dependency_address_specs(cls, kwargs=None, payload=None):
        for address_spec in super().compute_dependency_address_specs(kwargs, payload):
            yield address_spec

        for address_spec in ScalaPlatform.global_instance().injectables_address_specs_for_key(
            "scalac"
        ):
            yield address_spec
