# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.java.jar.jar_dependency import JarDependency


class ScalaJarDependency(JarDependency):
    """A JarDependency with the configured '--scala-platform-version' automatically appended.

    This allows for more natural consumption of cross-published scala libraries, which have their
    scala version/platform appended to the artifact name.
    """

    @property
    def name(self):
        return ScalaPlatform.global_instance().suffix_version(self.base_name)
