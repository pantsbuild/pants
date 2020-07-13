# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from textwrap import dedent
from typing import List, Optional

from pants.backend.python.lint.pylint.plugin_target_type import PylintSourcePlugin
from pants.backend.python.lint.pylint.rules import PylintFieldSet, PylintRequest
from pants.backend.python.lint.pylint.rules import rules as pylint_rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.goals.lint import LintResults
from pants.engine.addresses import Address
from pants.engine.fs import FileContent
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import TargetWithOrigin, WrappedTarget
from pants.python.python_requirement import PythonRequirement
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.interpreter_selection_utils import skip_unless_python27_and_python3_present
from pants.testutil.option.util import create_options_bootstrapper

# See http://pylint.pycqa.org/en/latest/user_guide/run.html#exit-codes for exit codes.
PYLINT_FAILURE_RETURN_CODE = 16


class PylintIntegrationTest(ExternalToolTestBase):
    source_root = "src/python"
    good_source = FileContent(
        f"{source_root}/good.py", b"'''docstring'''\nUPPERCASE_CONSTANT = ''\n",
    )
    bad_source = FileContent(
        f"{source_root}/bad.py", b"'''docstring'''\nlowercase_constant = ''\n",
    )
    py3_only_source = FileContent(
        f"{source_root}/py3.py", b"'''docstring'''\nCONSTANT: str = ''\n",
    )

    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(objects={"python_requirement": PythonRequirement})

    @classmethod
    def target_types(cls):
        return [PythonLibrary, PythonRequirementLibrary, PylintSourcePlugin]

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *pylint_rules(),
            RootRule(PylintRequest),
            RootRule(HydratedTargets),
        )

    def make_target_with_origin(
        self,
        source_files: List[FileContent],
        *,
        name: str = "target",
        interpreter_constraints: Optional[str] = None,
        origin: Optional[OriginSpec] = None,
        dependencies: Optional[List[Address]] = None,
    ) -> TargetWithOrigin:
        for source_file in source_files:
            self.create_file(source_file.path, source_file.content.decode())
        source_globs = [PurePath(source_file.path).name for source_file in source_files]
        self.add_to_build_file(
            self.source_root,
            dedent(
                f"""\
                python_library(
                    name={repr(name)},
                    sources={source_globs},
                    dependencies={[str(dep) for dep in dependencies or ()]},
                    compatibility={repr(interpreter_constraints)},
                )
                """
            ),
        )
        target = self.request_single_product(WrappedTarget, Address(self.source_root, name)).target
        if origin is None:
            origin = SingleAddress(directory=self.source_root, name=name)
        return TargetWithOrigin(target, origin)

    def run_pylint(
        self,
        targets: List[TargetWithOrigin],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
        additional_args: Optional[List[str]] = None,
    ) -> LintResults:
        args = [
            "--backend-packages2=pants.backend.python.lint.pylint",
            "--source-root-patterns=src/python",
        ]
        if config:
            self.create_file(relpath="pylintrc", contents=config)
            args.append("--pylint-config=pylintrc")
        if passthrough_args:
            args.append(f"--pylint-args='{passthrough_args}'")
        if skip:
            args.append("--pylint-skip")
        if additional_args:
            args.extend(additional_args)
        return self.request_single_product(
            LintResults,
            Params(
                PylintRequest(PylintFieldSet.create(tgt) for tgt in targets),
                create_options_bootstrapper(args=args),
            ),
        )

    def test_passing_source(self) -> None:
        target = self.make_target_with_origin([self.good_source])
        result = self.run_pylint([target])
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()

    def test_failing_source(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target])
        assert len(result) == 1
        assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
        assert "bad.py:2:0: C0103" in result[0].stdout

    def test_mixed_sources(self) -> None:
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        result = self.run_pylint([target])
        assert len(result) == 1
        assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
        assert "good.py" not in result[0].stdout
        assert "bad.py:2:0: C0103" in result[0].stdout

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source], name="t1"),
            self.make_target_with_origin([self.bad_source], name="t2"),
        ]
        result = self.run_pylint(targets)
        assert len(result) == 1
        assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
        assert "good.py" not in result[0].stdout
        assert "bad.py:2:0: C0103" in result[0].stdout

    def test_precise_file_args(self) -> None:
        target = self.make_target_with_origin(
            [self.good_source, self.bad_source], origin=FilesystemLiteralSpec(self.good_source.path)
        )
        result = self.run_pylint([target])
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()

    @skip_unless_python27_and_python3_present
    def test_uses_correct_python_version(self) -> None:
        py2_args = [
            "--pylint-version=pylint<2",
            "--pylint-extra-requirements=['setuptools<45', 'isort>=4.3.21,<4.4']",
        ]
        py2_target = self.make_target_with_origin(
            [self.py3_only_source], name="py2", interpreter_constraints="CPython==2.7.*"
        )
        py2_result = self.run_pylint([py2_target], additional_args=py2_args)
        assert len(py2_result) == 1
        assert py2_result[0].exit_code == 2
        assert "invalid syntax (<string>, line 2) (syntax-error)" in py2_result[0].stdout

        py3_target = self.make_target_with_origin(
            [self.py3_only_source], name="py3", interpreter_constraints="CPython>=3.6"
        )
        py3_result = self.run_pylint([py3_target])
        assert len(py3_result) == 1
        assert py3_result[0].exit_code == 0
        assert "Your code has been rated at 10.00/10" in py3_result[0].stdout.strip()

        combined_result = self.run_pylint([py2_target, py3_target], additional_args=py2_args)
        assert len(combined_result) == 2
        batched_py3_result, batched_py2_result = sorted(
            combined_result, key=lambda result: result.exit_code
        )
        assert batched_py2_result.exit_code == 2
        assert "invalid syntax (<string>, line 2) (syntax-error)" in batched_py2_result.stdout
        assert batched_py3_result.exit_code == 0
        assert "Your code has been rated at 10.00/10" in batched_py3_result.stdout.strip()

    def test_respects_config_file(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target], config="[pylint]\ndisable = C0103\n")
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()

    def test_respects_passthrough_args(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target], passthrough_args="--disable=C0103")
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()

    def test_includes_direct_dependencies(self) -> None:
        self.add_to_build_file(
            "",
            dedent(
                """\
                python_requirement_library(
                    name='transitive_req',
                    requirements=[python_requirement('django')],
                )

                python_requirement_library(
                    name='direct_req',
                    requirements=[python_requirement('ansicolors')],
                )
                """
            ),
        )
        self.add_to_build_file(
            self.source_root, "python_library(name='transitive_dep', sources=[])\n"
        )
        self.create_file(
            f"{self.source_root}/direct_dep.py",
            dedent(
                """\
                # No docstring - Pylint doesn't lint dependencies.

                from transitive_dep import doesnt_matter_if_variable_exists

                THIS_VARIABLE_EXISTS = ''
                """
            ),
        )
        self.add_to_build_file(
            self.source_root,
            dedent(
                """\
                python_library(
                    name='direct_dep',
                    sources=['direct_dep.py'],
                    dependencies=[':transitive_dep', '//:transitive_req'],
                )
                """
            ),
        )

        source_content = dedent(
            """\
            '''Pylint will check that variables exist and are used.'''
            from colors import green
            from direct_dep import THIS_VARIABLE_EXISTS

            print(green(THIS_VARIABLE_EXISTS))
            """
        )
        target = self.make_target_with_origin(
            source_files=[FileContent(f"{self.source_root}/target.py", source_content.encode())],
            dependencies=[Address(self.source_root, "direct_dep"), Address("", "direct_req")],
        )

        result = self.run_pylint([target])
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target], skip=True)
        assert not result

    def test_3rdparty_plugin(self) -> None:
        source_content = dedent(
            """\
            '''Docstring.'''

            import unittest

            class PluginTest(unittest.TestCase):
                '''Docstring.'''

                def test_plugin(self):
                    '''Docstring.'''
                    self.assertEqual(True, True)
            """
        )
        target = self.make_target_with_origin(
            [FileContent(f"{self.source_root}/thirdparty_plugin.py", source_content.encode())]
        )
        result = self.run_pylint(
            [target],
            additional_args=["--pylint-extra-requirements=pylint-unittest>=0.1.3,<0.2"],
            passthrough_args="--load-plugins=pylint_unittest",
        )
        assert len(result) == 1
        assert result[0].exit_code == 4
        assert "thirdparty_plugin.py:10:8: W5301" in result[0].stdout

    def test_source_plugin(self) -> None:
        # NB: We make this source plugin fairly complex by having it use transitive dependencies.
        # This is to ensure that we can correctly support plugins with dependencies.
        self.add_to_build_file(
            "",
            dedent(
                """\
                python_requirement_library(
                    name='pylint',
                    requirements=[python_requirement('pylint>=2.4.4,<2.5')],
                )

                python_requirement_library(
                    name='colors',
                    requirements=[python_requirement('ansicolors')],
                )
                """
            ),
        )
        self.create_file(
            "build-support/plugins/subdir/dep.py",
            dedent(
                """\
                from colors import red

                def is_print(node):
                    _ = red("Test that transitive deps are loaded.")
                    return node.func.name == "print"
                """
            ),
        )
        self.add_to_build_file(
            "build-support/plugins/subdir", "python_library(dependencies=['//:colors'])"
        )
        self.create_file(
            "build-support/plugins/print_plugin.py",
            dedent(
                """\
                from pylint.checkers import BaseChecker
                from pylint.interfaces import IAstroidChecker

                from subdir.dep import is_print

                class PrintChecker(BaseChecker):
                    __implements__ = IAstroidChecker
                    name = "print_plugin"
                    msgs = {
                        "C9871": ("`print` statements are banned", "print-statement-used", ""),
                    }

                    def visit_call(self, node):
                        if is_print(node):
                            self.add_message("print-statement-used", node=node)

                def register(linter):
                    linter.register_checker(PrintChecker(linter))
                """
            ),
        )
        self.add_to_build_file(
            "build-support/plugins",
            dedent(
                """\
                pylint_source_plugin(
                    name='print_plugin',
                    sources=['print_plugin.py'],
                    dependencies=['//:pylint', 'build-support/plugins/subdir'],
                )
                """
            ),
        )
        config_content = dedent(
            """\
            [MASTER]
            load-plugins=print_plugin
            """
        )
        target = self.make_target_with_origin(
            [FileContent(f"{self.source_root}/source_plugin.py", b"'''Docstring.'''\nprint()\n")]
        )
        result = self.run_pylint(
            [target],
            additional_args=[
                "--pylint-source-plugins=['build-support/plugins:print_plugin']",
                f"--source-root-patterns=['build-support/plugins', '{self.source_root}']",
            ],
            config=config_content,
        )
        assert len(result) == 1
        assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
        assert "source_plugin.py:2:0: C9871" in result[0].stdout
