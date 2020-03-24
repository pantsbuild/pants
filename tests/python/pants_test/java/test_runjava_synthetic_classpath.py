# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.java import util
from pants.net.http.fetcher import Fetcher
from pants.testutil.jvm.nailgun_task_test_base import NailgunTaskTestBase
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_concurrent_rename


class DummyRunJavaTask(NailgunTask):
    def execute(self):
        pass


class SyntheticClasspathTest(NailgunTaskTestBase):
    @classmethod
    def task_type(cls):
        return DummyRunJavaTask

    def test_execute_java_no_error_weird_path(self):
        """
        :API: public
        """
        with temporary_file(suffix=".jar") as temp_path:
            fetcher = Fetcher(get_buildroot())
            try:
                # Download a jar that echoes things.
                fetcher.download(
                    "https://maven-central.storage-download.googleapis.com/maven2/io/get-coursier/echo/1.0.0/echo-1.0.0.jar",
                    path_or_fd=temp_path.name,
                    timeout_secs=2,
                )
            except fetcher.Error:
                self.fail("fail to download echo jar")

            task = self.execute(self.context([]))
            executor = task.create_java_executor()

            # Executing the jar as is should work.
            self.assertEqual(
                0,
                util.execute_java(
                    executor=executor,
                    classpath=[temp_path.name],
                    main="coursier.echo.Echo",
                    args=["Hello World"],
                    create_synthetic_jar=True,
                ),
            )

            # Rename the jar to contain reserved characters.
            new_path = os.path.join(os.path.dirname(temp_path.name), "%%!!!===++.jar")
            safe_concurrent_rename(temp_path.name, new_path)

            # Executing the new path should work.
            self.assertEqual(
                0,
                util.execute_java(
                    executor=executor,
                    classpath=[new_path],
                    main="coursier.echo.Echo",
                    args=["Hello World"],
                    create_synthetic_jar=True,
                ),
            )
