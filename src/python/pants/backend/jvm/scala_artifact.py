# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform


class ScalaArtifact(Artifact):
    """Extends Artifact to append the configured Scala version.

    :API: public
    """

    @property
    def name(self):
        return ScalaPlatform.global_instance().suffix_version(self._base_name)

    @name.setter
    def name(self, value):
        self._base_name = ScalaPlatform.global_instance().suffix_version(value)
