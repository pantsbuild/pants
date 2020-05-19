# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_compile.compile_context import CompileContext
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import BaseZincCompile
from pants.testutil.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase
from pants.util.contextutil import temporary_file_path


class ZincCompileTest(JvmToolTaskTestBase):
    @classmethod
    def task_type(cls):
        return BaseZincCompile

    def setUp(self):
        super().setUp()

        self.java_target = self.make_target(":java", target_type=JavaLibrary)

    def get_task(self, specs=[]):
        context = self.context(target_roots=[self.target(spec) for spec in specs])
        task = self.create_task(context)
        return task

    def test_spaces_preserved_when_populating_zinc_args_product_from_argfile(self):
        with temporary_file_path() as arg_file_path:
            compile_contexts = {
                self.java_target: CompileContext(
                    self.java_target,
                    analysis_file="",
                    classes_dir="",
                    jar_file="",
                    log_dir="",
                    args_file=arg_file_path,
                    sources=[],
                    post_compile_merge_dir="",
                    diagnostics_out=None,
                )
            }
            task = self.get_task()
            args = ["-classpath", "a.jar:b.jar", "-C-Xplugin:some_javac_plugin with args"]
            task.context.products.safe_create_data(
                "zinc_args", init_func=lambda: {self.java_target: []}
            )
            task.write_argsfile(compile_contexts[self.java_target], args)
            task.register_extra_products_from_contexts([self.java_target], compile_contexts)
            zinc_args = task.context.products.get_data("zinc_args")[self.java_target]
            assert args == zinc_args
