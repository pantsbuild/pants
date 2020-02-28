# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jvm_target import JvmTarget


class ExportableJvmLibrary(JvmTarget):
    """A baseclass for java targets that support being exported to an artifact repository.

    :API: public
    """

    def __init__(self, *args, **kwargs):
        """
        :param :class:`pants.backend.jvm.artifact.Artifact` provides:
          An optional object indicating the ivy artifact to export.
        """
        # TODO: Move provides argument out of the parent class and onto this one?
        super().__init__(*args, **kwargs)
