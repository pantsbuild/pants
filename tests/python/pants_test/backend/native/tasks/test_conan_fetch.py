# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.native.targets.external_native_library import ExternalNativeLibrary
from pants.backend.native.tasks.conan_fetch import ConanFetch
from pants.backend.native.tasks.conan_prep import ConanPrep
from pants.testutil.task_test_base import TaskTestBase


class ConanFetchTest(TaskTestBase):
    @classmethod
    def task_type(cls):
        return ConanFetch

    def test_conan_pex_noop(self):
        """Test that the conan pex is not generated if there are no conan libraries to fetch."""
        conan_prep_task_type = self.synthesize_task_subtype(ConanPrep, "conan_prep_scope")
        context = self.context(for_task_types=[conan_prep_task_type])
        conan_prep = conan_prep_task_type(context, os.path.join(self.pants_workdir, "conan_prep"))
        conan_prep.execute()
        self.assertIsNone(context.products.get_data(ConanPrep.tool_instance_cls))

    def test_rewrites_remotes_according_to_options(self):
        self.set_options(conan_remotes={"pants-conan": "https://conan.bintray.com"})
        conan_prep_task_type = self.synthesize_task_subtype(ConanPrep, "conan_prep_scope")
        # We need at least one library to resolve here so that the conan pex is generated.
        dummy_target = self.make_target(
            spec="//:dummy-conan-3rdparty-lib", target_type=ExternalNativeLibrary, packages=[]
        )
        context = self.context(for_task_types=[conan_prep_task_type], target_roots=[dummy_target])
        conan_prep = conan_prep_task_type(context, os.path.join(self.pants_workdir, "conan_prep"))
        conan_fetch = self.create_task(context, os.path.join(self.pants_workdir, "conan_fetch"))
        conan_prep.execute()
        conan_fetch.execute()
        conan_pex = context.products.get_data(ConanPrep.tool_instance_cls)
        user_home = conan_fetch._conan_user_home(conan_pex, in_workdir=True)

        (stdout, stderr, exit_code, _) = conan_pex.output(
            ["remote", "list"], env={"CONAN_USER_HOME": user_home}
        )
        self.assertEqual(0, exit_code)
        self.assertEqual(stdout, "pants-conan: https://conan.bintray.com [Verify SSL: True]\n")
