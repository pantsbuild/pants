# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.jvm.subsystems.junit import JUnit
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.target import Target
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.test_base import TestBase


class JUnitTestsTest(TestBase):
    def test_validation(self):
        init_subsystem(JUnit)
        target = self.make_target("//:mybird", Target)
        # A plain invocation with no frills
        test1 = self.make_target(
            "//:test1", JUnitTests, sources=["Test.java"], dependencies=[target]
        )
        self.assertIsNone(test1.cwd)
        self.assertIsNone(test1.concurrency)
        self.assertIsNone(test1.threads)
        self.assertIsNone(test1.timeout)

        # cwd parameter
        testcwd = self.make_target(
            "//:testcwd1", JUnitTests, sources=["Test.java"], concurrency="SERIAL", cwd="/foo/bar"
        )
        self.assertEqual("/foo/bar", testcwd.cwd)

        # concurrency parameter
        tc1 = self.make_target(
            "//:testconcurrency1", JUnitTests, sources=["Test.java"], concurrency="SERIAL"
        )
        self.assertEqual(JUnitTests.CONCURRENCY_SERIAL, tc1.concurrency)
        tc2 = self.make_target(
            "//:testconcurrency2", JUnitTests, sources=["Test.java"], concurrency="PARALLEL_CLASSES"
        )
        self.assertEqual(JUnitTests.CONCURRENCY_PARALLEL_CLASSES, tc2.concurrency)
        tc3 = self.make_target(
            "//:testconcurrency3", JUnitTests, sources=["Test.java"], concurrency="PARALLEL_METHODS"
        )
        self.assertEqual(JUnitTests.CONCURRENCY_PARALLEL_METHODS, tc3.concurrency)
        tc4 = self.make_target(
            "//:testconcurrency4",
            JUnitTests,
            sources=["Test.java"],
            concurrency="PARALLEL_CLASSES_AND_METHODS",
        )
        self.assertEqual(JUnitTests.CONCURRENCY_PARALLEL_CLASSES_AND_METHODS, tc4.concurrency)
        with self.assertRaisesRegex(TargetDefinitionException, r"concurrency"):
            self.make_target(
                "//:testconcurrency5", JUnitTests, sources=["Test.java"], concurrency="nonsense"
            )

        # threads parameter
        tt1 = self.make_target("//:testthreads1", JUnitTests, sources=["Test.java"], threads=99)
        self.assertEqual(99, tt1.threads)
        tt2 = self.make_target("//:testthreads2", JUnitTests, sources=["Test.java"], threads="123")
        self.assertEqual(123, tt2.threads)
        with self.assertRaisesRegex(TargetDefinitionException, r"threads"):
            self.make_target("//:testthreads3", JUnitTests, sources=["Test.java"], threads="abc")

        # timeout parameter
        timeout = self.make_target(
            "//:testtimeout1", JUnitTests, sources=["Test.java"], timeout=999
        )
        self.assertEqual(999, timeout.timeout)

    def test_implicit_junit_dep(self):
        init_subsystem(JUnit)
        # Check that the implicit dep is added, and doesn't replace other deps.
        target = self.make_target("//:target", Target)
        test1 = self.make_target("//:test1", JUnitTests, sources=[], dependencies=[target])
        self.assertEqual(
            ["JarLibrary(//:junit_library)", "Target(//:target)"],
            sorted(str(x) for x in test1.dependencies),
        )

        # Check that having an explicit dep doesn't cause problems.
        junit_target = self.build_graph.get_target_from_spec("//:junit_library")
        test2 = self.make_target(
            "//:test2", JUnitTests, sources=[], dependencies=[junit_target, target]
        )
        self.assertEqual(
            ["JarLibrary(//:junit_library)", "Target(//:target)"],
            sorted(str(x) for x in test2.dependencies),
        )
