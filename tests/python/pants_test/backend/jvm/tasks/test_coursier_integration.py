# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class CoursierIntegrationTest(PantsRunIntegrationTest):
    def test_coursier_show_report(self):
        with self.temporary_workdir() as workdir:
            # Run the coursier report twice in a row with the same workdir to check that
            # --report forces a resolve even though the task is validated.
            for _ in range(2):
                pants_run = self.run_pants_with_workdir(
                    command=[
                        "--resolver-resolver=coursier",
                        "--resolve-coursier-report",
                        "resolve",
                        "examples/tests/scala/org/pantsbuild/example/hello/welcome:welcome",
                    ],
                    workdir=workdir,
                )
                self.assert_success(pants_run)
                # Coursier report looks like this:
                #    Result:
                #  ├─ org.scala-lang:scala-library:2.11.11
                #  ├─ junit:junit:4.12
                #  │  └─ org.hamcrest:hamcrest-core:1.3
                #  └─ org.scalatest:scalatest_2.11:3.0.0
                #     ├─ org.scala-lang:scala-library:2.11.8 -> 2.11.11
                #     ├─ org.scala-lang:scala-reflect:2.11.8
                #     │  └─ org.scala-lang:scala-library:2.11.8 -> 2.11.11
                #     ├─ org.scala-lang.modules:scala-parser-combinators_2.11:1.0.4
                #     │  └─ org.scala-lang:scala-library:2.11.6 -> 2.11.11
                #     ├─ org.scala-lang.modules:scala-xml_2.11:1.0.5
                #     │  └─ org.scala-lang:scala-library:2.11.7 -> 2.11.11
                #     └─ org.scalactic:scalactic_2.11:3.0.0
                #        ├─ org.scala-lang:scala-library:2.11.8 -> 2.11.11
                #        └─ org.scala-lang:scala-reflect:2.11.8
                #           └─ org.scala-lang:scala-library:2.11.8 -> 2.11.11
                #  /Users/me/.cache/pants/coursier/https/repo1.maven.org/maven2/org/scala-lang/modules/scala-xml_2.11/1.0.5/scala-xml_2.11-1.0.5.jar
                #  /Users/me/.cache/pants/coursier/https/repo1.maven.org/maven2/org/scala-lang/modules/scala-parser-combinators_2.11/1.0.4/scala-parser-combinators_2.11-1.0.4.jar
                #  /Users/me/.cache/pants/coursier/https/repo1.maven.org/maven2/junit/junit/4.12/junit-4.12.jar
                #  /Users/me/.cache/pants/coursier/https/repo1.maven.org/maven2/org/scala-lang/scala-reflect/2.11.8/scala-reflect-2.11.8.jar
                #  /Users/me/.cache/pants/coursier/https/repo1.maven.org/maven2/org/scalatest/scalatest_2.11/3.0.0/scalatest_2.11-3.0.0.jar
                #  /Users/me/.cache/pants/coursier/https/repo1.maven.org/maven2/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar
                #  /Users/me/.cache/pants/coursier/https/repo1.maven.org/maven2/org/scala-lang/scala-library/2.11.11/scala-library-2.11.11.jar
                #  /Users/me/.cache/pants/coursier/https/repo1.maven.org/maven2/org/scalactic/scalactic_2.11/3.0.0/scalactic_2.11-3.0.0.jar
                self.assertIn("Result:", pants_run.stdout_data)
                self.assertIn("junit:junit:4.12", pants_run.stdout_data)

    def test_coursier_no_report(self):
        pants_run = self.run_pants(
            [
                "--resolver-resolver=coursier",
                "resolve",
                "examples/tests/scala/org/pantsbuild/example/hello/welcome:welcome",
            ]
        )
        self.assert_success(pants_run)
        self.assertNotIn("Result:", pants_run.stdout_data)
