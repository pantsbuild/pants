# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.backend.project_info.tasks.idea_plugin_gen import IdeaPluginGen


class IdeaPluginTest(unittest.TestCase):
    def test_project_name(self) -> None:
        targets = [
            "examples/src/scala/org/pantsbuild/example/hello:",
            "testprojects/src/python/sources::",
        ]
        self.assertEqual(
            "examples.src.scala.org.pantsbuild.example.hello:__testprojects.src.python.sources::",
            IdeaPluginGen.get_project_name(targets),
        )

    def test_long_project_name(self) -> None:
        targets = [
            "examples/src/scala/org/pantsbuild/example/hello/really/long/fake/project/name:",
            "testprojects/src/python/print_env::",
            "testprojects/src/python/sources::",
            "testprojects/src/python/unicode::",
            "testprojects/src/python/another/long/project/name::",
        ]
        self.assertGreater(len("".join(targets)), IdeaPluginGen.PROJECT_NAME_LIMIT)
        self.assertEqual(
            (
                "examples.src.scala.org.pantsbuild.example.hello.really.long.fake.project.name:"
                "__testprojects.src.python.print_env::"
                "__testprojects.src.python.sources::"
                "__testprojects.src.python.unicode::"
                "__testprojects.src.python.another.long.project.name::"
            )[: IdeaPluginGen.PROJECT_NAME_LIMIT],
            IdeaPluginGen.get_project_name(targets),
        )
