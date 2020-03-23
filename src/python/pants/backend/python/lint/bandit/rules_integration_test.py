# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.backend.python.lint.bandit.rules import BanditLinter
from pants.backend.python.lint.bandit.rules import rules as bandit_rules
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.fs import FileContent, InputFilesContent, Snapshot
from pants.engine.legacy.structs import PythonTargetAdaptor, PythonTargetAdaptorWithOrigin
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.lint import LintResult
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class BanditIntegrationTest(TestBase):

    good_source = FileContent(path="test/good.py", content=b"hashlib.sha256()\n")
    # MD5 is a insecure hashing function
    bad_source = FileContent(path="test/bad.py", content=b"hashlib.md5()\n")

    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(targets={"python_library": PythonLibrary})

    @classmethod
    def rules(cls):
        return (*super().rules(), *bandit_rules(), RootRule(BanditLinter))

    def make_target_with_origin(
        self,
        source_files: List[FileContent],
        *,
        interpreter_constraints: Optional[str] = None,
        origin: Optional[OriginSpec] = None,
    ) -> PythonTargetAdaptorWithOrigin:
        input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
        adaptor_kwargs = dict(
            sources=EagerFilesetWithSpec("test", {"globs": []}, snapshot=input_snapshot),
            address=Address.parse("test:target"),
        )
        if interpreter_constraints:
            adaptor_kwargs["compatibility"] = interpreter_constraints
        if origin is None:
            origin = SingleAddress(directory="test", name="target")
        return PythonTargetAdaptorWithOrigin(PythonTargetAdaptor(**adaptor_kwargs), origin)

    def run_bandit(
        self,
        targets: List[PythonTargetAdaptorWithOrigin],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
    ) -> LintResult:
        args = ["--backend-packages2=pants.backend.python.lint.bandit"]
        if config:
            self.create_file(relpath=".bandit", contents=config)
            args.append("--bandit-config=.bandit")
        if passthrough_args:
            args.append(f"--bandit-args={passthrough_args}")
        if skip:
            args.append(f"--bandit-skip")
        return self.request_single_product(
            LintResult,
            Params(BanditLinter(tuple(targets)), create_options_bootstrapper(args=args)),
        )

    def test_passing_source(self) -> None:
        target = self.make_target_with_origin([self.good_source])
        result = self.run_bandit([target])
        assert result.exit_code == 0
        assert "No issues identified." in result.stdout.strip()

    def test_failing_source(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_bandit([target])
        assert result.exit_code == 1
        assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result.stdout

    def test_mixed_sources(self) -> None:
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        result = self.run_bandit([target])
        assert result.exit_code == 1
        assert "test/good.py" not in result.stdout
        assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result.stdout

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source]),
            self.make_target_with_origin([self.bad_source]),
        ]
        result = self.run_bandit(targets)
        assert result.exit_code == 1
        assert "test/good.py" not in result.stdout
        assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result.stdout

    def test_precise_file_args(self) -> None:
        target = self.make_target_with_origin(
            [self.good_source, self.bad_source], origin=FilesystemLiteralSpec(self.good_source.path)
        )
        result = self.run_bandit([target])
        assert result.exit_code == 0
        assert "No issues identified." in result.stdout

    def test_respects_config_file(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_bandit([target], config="skips: ['B303']\n")
        assert result.exit_code == 0
        assert "No issues identified." in result.stdout.strip()

    def test_respects_passthrough_args(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_bandit([target], passthrough_args="--skip B303")
        assert result.exit_code == 0
        assert "No issues identified." in result.stdout.strip()

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_bandit([target], skip=True)
        assert result == LintResult.noop()
