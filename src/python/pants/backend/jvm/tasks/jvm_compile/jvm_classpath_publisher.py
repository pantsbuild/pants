# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.java.util import safe_classpath
from pants.task.task import Task
from pants.util.ordered_set import OrderedSet


class RuntimeClasspathPublisher(Task):
    """Create stable symlinks for runtime classpath entries for JVM targets."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--manifest-jar-only",
            type=bool,
            default=False,
            help="Only export classpath in a manifest jar.",
        )
        register(
            "--transitive-only",
            type=bool,
            default=False,
            help="Only export the classpath of the transitive dependencies of the target roots. "
            "This avoids jarring up the target roots themselves, which allows an IDE to "
            "insert their own modules more easily to cover the source files of target roots.",
        )

    @classmethod
    def prepare(cls, options, round_manager):
        round_manager.require_data("runtime_classpath")

    @property
    def _output_folder(self):
        return self.options_scope.replace(".", os.sep)

    def execute(self):
        basedir = os.path.join(self.get_options().pants_distdir, self._output_folder)
        runtime_classpath = self.context.products.get_data("runtime_classpath")

        targets = (
            OrderedSet(self.get_targets()) - set(self.context.target_roots)
            if self.get_options().transitive_only
            else self.get_targets()
        )

        if self.get_options().manifest_jar_only:
            classpath = ClasspathUtil.classpath(targets, runtime_classpath)
            # Safely create e.g. dist/export-classpath/manifest.jar
            safe_classpath(classpath, basedir, "manifest.jar")
        else:
            ClasspathProducts.create_canonical_classpath(
                runtime_classpath, targets, basedir, save_classpath_file=True
            )
