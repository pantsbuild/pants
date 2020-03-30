# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary


class AnnotationProcessor(ExportableJvmLibrary):
    """A Java library containing annotation processors.

    :API: public
    """

    def __init__(self, processors=None, *args, **kwargs):

        """
        :param processors: A list of the fully qualified class names of the
          annotation processors this library exports.
        """
        super().__init__(*args, **kwargs)
        self.processors = processors
