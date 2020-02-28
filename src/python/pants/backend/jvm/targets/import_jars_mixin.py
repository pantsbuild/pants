# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.import_remote_sources_mixin import ImportRemoteSourcesMixin
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf
from pants.util.ordered_set import OrderedSet


class ImportJarsMixin(ImportRemoteSourcesMixin):

    expected_target_constraint = SubclassesOf(JarLibrary)

    @memoized_property
    def all_imported_jar_deps(self):
        jar_deps = OrderedSet()
        for jar_lib in self.imported_targets:
            jar_deps.update(jar_lib.jar_dependencies)
        return list(jar_deps)
