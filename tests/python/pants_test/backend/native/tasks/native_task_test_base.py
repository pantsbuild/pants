# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pants.backend.native import register
from pants.backend.native.targets.native_library import CppLibrary
from pants.backend.native.tasks.conan_fetch import ConanFetch
from pants.backend.python.tasks.unpack_wheels import UnpackWheels
from pants.testutil.task_test_base import TaskTestBase


class NativeTaskTestBase(TaskTestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), *register.rules())


class NativeCompileTestMixin:
    def _retrieve_single_product_at_target_base(self, product_mapping, target):
        product = product_mapping.get(target)
        base_dirs = list(product.keys())
        self.assertEqual(1, len(base_dirs))
        single_base_dir = base_dirs[0]
        all_products = product[single_base_dir]
        self.assertEqual(1, len(all_products))
        single_product = all_products[0]
        return single_product

    def create_simple_cpp_library(self, **kwargs):
        self.create_file(
            "src/cpp/test/test.hpp",
            contents=dedent(
                """
                #ifndef __TEST_HPP__
                #define __TEST_HPP__

                int test(int);

                extern "C" int test_exported(int);

                #endif
                """
            ),
        )
        self.create_file(
            "src/cpp/test/test.cpp",
            contents=dedent(
                """
                #include "test.hpp"

                int test(int x) {
                  return x / 137;
                }

                extern "C" int test_exported(int x) {
                  return test(x * 42);
                }
                """
            ),
        )
        return self.make_target(
            spec="src/cpp/test", target_type=CppLibrary, sources=["test.hpp", "test.cpp"], **kwargs
        )

    def prepare_context_for_compile(self, target_roots, for_task_types=None, **kwargs):
        extract_python_wheels_task_type = self.synthesize_task_subtype(
            UnpackWheels, "extract_python_wheels_scope"
        )
        conan_fetch_task_type = self.synthesize_task_subtype(ConanFetch, "conan_fetch_scope")
        for_task_types = list(for_task_types or ()) + [
            extract_python_wheels_task_type,
            conan_fetch_task_type,
        ]
        context = self.context(target_roots=target_roots, for_task_types=for_task_types, **kwargs)

        extract_python_wheels = extract_python_wheels_task_type(
            context, os.path.join(self.pants_workdir, "extract_python_wheels")
        )
        conan_fetch = conan_fetch_task_type(
            context, os.path.join(self.pants_workdir, "conan_fetch")
        )

        extract_python_wheels.execute()
        conan_fetch.execute()
        return context
