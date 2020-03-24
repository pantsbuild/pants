# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.native.targets.native_library import CLibrary
from pants.backend.native.tasks.c_compile import CCompile
from pants.backend.native.tasks.native_compile import ObjectFiles
from pants_test.backend.native.tasks.native_task_test_base import (
    NativeCompileTestMixin,
    NativeTaskTestBase,
)


class CCompileTest(NativeTaskTestBase, NativeCompileTestMixin):
    @classmethod
    def task_type(cls):
        return CCompile

    def create_header_only_alternate_c_library(self, ext, **kwargs):
        header_filename = f"test{ext}"
        self.create_file(
            f"src/c/test/{header_filename}",
            contents=dedent(
                """
                #ifndef __TEST_H__
                #define __TEST_H__

                int test(int);

                #endif
                """
            ),
        )
        return self.make_target(
            spec="src/c/test", target_type=CLibrary, sources=[header_filename], **kwargs
        )

    def create_simple_c_library(self, **kwargs):
        self.create_file(
            "src/c/test/test.h",
            contents=dedent(
                """
                #ifndef __TEST_H__
                #define __TEST_H__

                int test(int);

                #endif
                """
            ),
        )
        self.create_file(
            "src/c/test/test.c",
            contents=dedent(
                """
                #include "test.h"

                int test(int x) {
                  return x / 137;
                }
                """
            ),
        )
        return self.make_target(
            spec="src/c/test", target_type=CLibrary, sources=["test.h", "test.c"], **kwargs
        )

    def test_header_only_noop_with_alternate_header_extension(self):
        alternate_extension = ".asdf"
        c = self.create_header_only_alternate_c_library(alternate_extension)
        context = self.prepare_context_for_compile(
            target_roots=[c],
            options={"c-compile-settings": {"header_file_extensions": [alternate_extension]}},
        )

        # Test that the task runs without error if provided a header-only library.
        c_compile = self.create_task(context)
        c_compile.execute()

        object_files_product = context.products.get(ObjectFiles)
        object_files_for_target = self._retrieve_single_product_at_target_base(
            object_files_product, c
        )
        # Test that no object files were produced.
        self.assertEqual(0, len(object_files_for_target.filenames))

    def test_caching(self):
        c = self.create_simple_c_library()
        context = self.prepare_context_for_compile(target_roots=[c])
        c_compile = self.create_task(context)

        # TODO: what is this testing?
        c_compile.execute()
        c_compile.execute()
