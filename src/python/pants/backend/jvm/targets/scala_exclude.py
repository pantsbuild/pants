# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.java.jar.exclude import Exclude


class ScalaExclude(Exclude):
    """Similar to its superclass, represents a (set of) jar coordinates to exclude.

    Overrides the `name` of the exclusion to append the '--scala-platform-version'. This allows
    for more natural consumption of cross-published scala libraries, which have their scala
    version/platform appended to the artifact name.

    :API: public
    """

    @property
    def name(self):
        base_name = super().name
        return ScalaPlatform.global_instance().suffix_version(base_name)
