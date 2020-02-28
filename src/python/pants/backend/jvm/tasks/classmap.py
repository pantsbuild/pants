# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.task.console_task import ConsoleTask


class ClassmapTask(ConsoleTask):
    """Print a mapping from class name to the owning target from target's runtime classpath."""

    _register_console_transitivity_option = False

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--transitive",
            default=True,
            type=bool,
            fingerprint=True,
            help="Include transitive dependencies in the classmap.",
        )
        register(
            "--internal-only",
            default=False,
            type=bool,
            fingerprint=True,
            help="Specifies that only class names of internal dependencies should be included.",
        )

    def classname_for_classfile(self, target, classpath_products):
        contents = ClasspathUtil.classpath_contents((target,), classpath_products)
        for f in contents:
            classname = ClasspathUtil.classname_for_rel_classfile(f)
            # None for non `.class` files
            if classname:
                yield classname

    def console_output(self, targets):
        def should_ignore(target):
            return self.get_options().internal_only and isinstance(target, JarLibrary)

        classpath_product = self.context.products.get_data("runtime_classpath")
        for target in targets:
            if not should_ignore(target):
                for file in self.classname_for_classfile(target, classpath_product):
                    yield f"{file} {target.address.spec}"

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data("runtime_classpath")
