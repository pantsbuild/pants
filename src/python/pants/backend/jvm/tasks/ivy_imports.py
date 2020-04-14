# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.tasks.classpath_entry import ArtifactClasspathEntry
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.coursier_resolve import CoursierMixin
from pants.backend.jvm.tasks.jar_import_products import JarImportProducts
from pants.backend.jvm.tasks.nailgun_task import NailgunTask


class IvyImports(CoursierMixin, NailgunTask):
    """Resolves jar files for imported_targets on `ImportJarsMixin` targets.

    One use case is for JavaProtobufLibrary, which includes imports for jars containing .proto
    files.
    """

    # TODO https://github.com/pantsbuild/pants/issues/604 product_types start
    @classmethod
    def product_types(cls):
        return [JarImportProducts]

    # TODO https://github.com/pantsbuild/pants/issues/604 product_types finish

    @staticmethod
    def has_imports(target):
        return isinstance(target, ImportJarsMixin) and target.imported_targets

    def execute(self):
        jar_import_products = self.context.products.get_data(
            JarImportProducts, init_func=JarImportProducts
        )

        # Gather all targets that are both capable of importing jars and actually declare some imports.
        targets = self.context.targets(predicate=self.has_imports)
        if not targets:
            return

        # Create a list of all of these targets plus the list of JarDependencies they depend on.
        all_targets = set(targets)
        for target in targets:
            all_targets.update(target.imported_targets)

        imports_classpath = ClasspathProducts(self.get_options().pants_workdir)
        self.resolve(
            targets=all_targets,
            compile_classpath=imports_classpath,
            sources=False,
            javadoc=False,
            executor=self.create_java_executor(),
        )

        for target in targets:
            cp_entries = imports_classpath.get_classpath_entries_for_targets(
                target.closure(bfs=True)
            )
            for conf, cp_entry in cp_entries:
                if isinstance(cp_entry, ArtifactClasspathEntry):
                    jar_import_products.imported(target, cp_entry.coordinate, cp_entry.path)
