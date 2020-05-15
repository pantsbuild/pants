# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.payload import Payload
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.cache.cache_setup import CacheFactory, CacheSetup
from pants.task.task import Task
from pants.testutil.task_test_base import TaskTestBase


class DummyLibrary(Target):
    def __init__(self, address, sources, *args, **kwargs):
        payload = Payload()
        payload.add_fields(
            {
                "sources": self.create_sources_field(
                    sources=sources, sources_rel_path=address.spec_path
                )
            }
        )
        super().__init__(address=address, payload=payload, *args, **kwargs)


class DummyTask(Task):
    options_scope = "dummy"

    @property
    def cache_target_dirs(self):
        return True

    def execute(self):
        self._cache_factory.get_write_cache()
        with self.invalidated(self.context.targets()) as invalidation:
            return invalidation.all_vts, invalidation.invalid_vts


class LocalCachingTest(TaskTestBase):

    _filename = "f"

    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(targets={"dummy_library": DummyLibrary})

    @classmethod
    def task_type(cls):
        return DummyTask

    def setUp(self):
        super().setUp()
        self.artifact_cache = self.create_dir("artifact_cache")
        self.create_file(self._filename)
        self.set_options_for_scope(
            CacheSetup.options_scope,
            write_to=[self.artifact_cache],
            read_from=[self.artifact_cache],
            write=True,
        )
        self.add_to_build_file("", f'dummy_library(name = "t", sources = ["{self._filename}"])')
        self._target = self.target(":t")
        context = self.context(for_task_types=[DummyTask], target_roots=[self._target])
        self.task = self.create_task(context)

    def test_cache_written_to(self):
        all_vts, invalid_vts = self.task.execute()
        self.assertGreater(len(invalid_vts), 0)
        for vt in invalid_vts:
            artifact_address = os.path.join(
                self.artifact_cache,
                CacheFactory.make_task_cache_dirname(self.task),
                self._target.id,
                f"{vt.cache_key.hash}.tgz",
            )
            self.assertTrue(os.path.isfile(artifact_address))

    def test_cache_read_from(self):
        all_vts, invalid_vts = self.task.execute()
        # Executing the task for the first time the vt is expected to be in the invalid_vts list
        self.assertGreater(len(invalid_vts), 0)
        first_vt = invalid_vts[0]
        # Mark the target invalid.
        self._target.mark_invalidation_hash_dirty()
        all_vts2, invalid_vts2 = self.task.execute()
        # Check that running the task a second time results in a valid vt,
        # implying the artifact cache was hit.
        self.assertGreater(len(all_vts2), 0)
        second_vt = all_vts2[0]
        self.assertEqual(first_vt.cache_key.hash, second_vt.cache_key.hash)
        self.assertListEqual(invalid_vts2, [])
