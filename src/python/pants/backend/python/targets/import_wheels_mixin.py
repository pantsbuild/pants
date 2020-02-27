# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.build_graph.import_remote_sources_mixin import ImportRemoteSourcesMixin
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf
from pants.util.ordered_set import OrderedSet


class ImportWheelsMixin(ImportRemoteSourcesMixin):

    expected_target_constraint = SubclassesOf(PythonRequirementLibrary)

    @memoized_property
    def all_imported_requirements(self):
        # TODO: figure out if this OrderedSet is necessary.
        all_requirements = OrderedSet()
        for req_lib in self.imported_targets:
            all_requirements.update(req_lib.requirements)
        return list(all_requirements)
