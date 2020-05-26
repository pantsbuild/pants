# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.backend.python.lint.flake8.rules import Flake8FieldSet, Flake8Request
from pants.backend.python.lint.flake8.rules import rules as flake8_rules
from pants.backend.python.target_types import PythonInterpreterCompatibility, PythonLibrary
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.core.goals.lint import LintResults
from pants.engine.addresses import Address
from pants.engine.fs import FileContent
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import TargetWithOrigin
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.interpreter_selection_utils import skip_unless_python27_and_python3_present
from pants.testutil.option.util import create_options_bootstrapper


class Flake8IntegrationTest(ExternalToolTestBase):

    good_source = FileContent(path="good.py", content=b"print('Nothing suspicious here..')\n")
    bad_source = FileContent(path="bad.py", content=b"import typing\n")  # unused import
    py3_only_source = FileContent(path="py3.py", content=b"version: str = 'Py3 > Py2'\n")

    @classmethod
    def rules(cls):
        return (*super().rules(), *flake8_rules(), RootRule(Flake8Request))

    def make_target_with_origin(
        self,
        source_files: List[FileContent],
        *,
        interpreter_constraints: Optional[str] = None,
        origin: Optional[OriginSpec] = None,
    ) -> TargetWithOrigin:
        for source_file in source_files:
            self.create_file(source_file.path, source_file.content.decode())
        target = PythonLibrary(
            {PythonInterpreterCompatibility.alias: interpreter_constraints},
            address=Address.parse(":target"),
        )
        if origin is None:
            origin = SingleAddress(directory="test", name="target")
        return TargetWithOrigin(target, origin)

    def run_flake8(
        self,
        targets: List[TargetWithOrigin],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
        additional_args: Optional[List[str]] = None,
    ) -> LintResults:
        args = ["--backend-packages2=pants.backend.python.lint.flake8"]
        if config:
            self.create_file(relpath=".flake8", contents=config)
            args.append("--flake8-config=.flake8")
        if passthrough_args:
            args.append(f"--flake8-args='{passthrough_args}'")
        if skip:
            args.append("--flake8-skip")
        if additional_args:
            args.extend(additional_args)
        return self.request_single_product(
            LintResults,
            Params(
                Flake8Request(Flake8FieldSet.create(tgt) for tgt in targets),
                create_options_bootstrapper(args=args),
            ),
        )

    def test_passing_source(self) -> None:
        target = self.make_target_with_origin([self.good_source])
        result = self.run_flake8([target])
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert result[0].stdout.strip() == ""

    def test_failing_source(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_flake8([target])
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert "bad.py:1:1: F401" in result[0].stdout

    def test_mixed_sources(self) -> None:
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        result = self.run_flake8([target])
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert "good.py" not in result[0].stdout
        assert "bad.py:1:1: F401" in result[0].stdout

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source]),
            self.make_target_with_origin([self.bad_source]),
        ]
        result = self.run_flake8(targets)
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert "good.py" not in result[0].stdout
        assert "bad.py:1:1: F401" in result[0].stdout

    def test_precise_file_args(self) -> None:
        target = self.make_target_with_origin(
            [self.good_source, self.bad_source], origin=FilesystemLiteralSpec(self.good_source.path)
        )
        result = self.run_flake8([target])
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert result[0].stdout.strip() == ""

    @skip_unless_python27_and_python3_present
    def test_uses_correct_python_version(self) -> None:
        py2_target = self.make_target_with_origin(
            [self.py3_only_source], interpreter_constraints="CPython==2.7.*"
        )
        py2_result = self.run_flake8([py2_target])
        assert len(py2_result) == 1
        assert py2_result[0].exit_code == 1
        assert "py3.py:1:8: E999 SyntaxError" in py2_result[0].stdout

        py3_target = self.make_target_with_origin(
            [self.py3_only_source], interpreter_constraints="CPython>=3.6"
        )
        py3_result = self.run_flake8([py3_target])
        assert len(py3_result) == 1
        assert py3_result[0].exit_code == 0
        assert py3_result[0].stdout.strip() == ""

        # Test that we partition incompatible targets when passed in a single batch. We expect Py2
        # to still fail, but Py3 should pass.
        combined_result = self.run_flake8([py2_target, py3_target])
        assert len(combined_result) == 2
        batched_py3_result, batched_py2_result = sorted(
            combined_result, key=lambda result: result.exit_code
        )
        assert batched_py2_result.exit_code == 1
        assert "py3.py:1:8: E999 SyntaxError" in batched_py2_result.stdout
        assert batched_py3_result.exit_code == 0
        assert batched_py3_result.stdout.strip() == ""

    def test_respects_config_file(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_flake8([target], config="[flake8]\nignore = F401\n")
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert result[0].stdout.strip() == ""

    def test_respects_passthrough_args(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_flake8([target], passthrough_args="--ignore=F401")
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert result[0].stdout.strip() == ""

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_flake8([target], skip=True)
        assert not result

    def test_3rdparty_plugin(self) -> None:
        target = self.make_target_with_origin(
            [FileContent("bad.py", b"'constant' and 'constant2'\n")]
        )
        result = self.run_flake8(
            [target], additional_args=["--flake8-extra-requirements=flake8-pantsbuild>=2.0,<3"]
        )
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert "bad.py:1:1: PB11" in result[0].stdout
