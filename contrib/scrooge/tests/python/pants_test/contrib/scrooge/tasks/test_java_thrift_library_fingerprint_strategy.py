# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.thrift.java.thrift_defaults import ThriftDefaults
from pants.testutil.test_base import TestBase

from pants.contrib.scrooge.tasks.java_thrift_library_fingerprint_strategy import (
    JavaThriftLibraryFingerprintStrategy,
)


class JavaThriftLibraryFingerprintStrategyTest(TestBase):

    options1 = {"compiler": "scrooge", "language": "java", "compiler_args": []}

    def create_strategy(self, option_values):
        self.context(
            for_subsystems=[ThriftDefaults], options={ThriftDefaults.options_scope: option_values}
        )
        return JavaThriftLibraryFingerprintStrategy(ThriftDefaults.global_instance())

    def test_fp_diffs_due_to_option(self):
        option_values = {"compiler": "scrooge", "language": "java", "compiler_args": ["--foo"]}

        a = self.make_target(":a", target_type=JavaThriftLibrary)

        fp1 = self.create_strategy(self.options1).compute_fingerprint(a)
        fp2 = self.create_strategy(option_values).compute_fingerprint(a)
        self.assertNotEqual(fp1, fp2)

    def test_fp_diffs_due_to_compiler_args_change(self):
        a = self.make_target(":a", target_type=JavaThriftLibrary, compiler_args=["--foo"])
        b = self.make_target(":b", target_type=JavaThriftLibrary, compiler_args=["--bar"])

        fp1 = self.create_strategy(self.options1).compute_fingerprint(a)
        fp2 = self.create_strategy(self.options1).compute_fingerprint(b)
        self.assertNotEqual(fp1, fp2)

    def test_hash_and_equal(self):
        self.assertEqual(self.create_strategy(self.options1), self.create_strategy(self.options1))
        self.assertEqual(
            hash(self.create_strategy(self.options1)), hash(self.create_strategy(self.options1))
        )

        option_values = {"compiler": "scrooge", "language": "java", "compiler_args": ["--baz"]}
        self.assertNotEqual(
            self.create_strategy(self.options1), self.create_strategy(option_values)
        )
        self.assertNotEqual(
            hash(self.create_strategy(self.options1)), hash(self.create_strategy(option_values))
        )
