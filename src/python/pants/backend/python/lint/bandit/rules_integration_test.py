# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.backend.python.lint.bandit.rules import BanditFieldSet, BanditFieldSets
from pants.backend.python.lint.bandit.rules import rules as bandit_rules
from pants.backend.python.target_types import PythonInterpreterCompatibility, PythonLibrary
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.core.goals.lint import LintResult
from pants.engine.addresses import Address
from pants.engine.fs import FileContent
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import TargetWithOrigin
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.option.util import create_options_bootstrapper


class BanditIntegrationTest(ExternalToolTestBase):

    good_source = FileContent(path="good.py", content=b"hashlib.sha256()\n")
    # MD5 is a insecure hashing function
    bad_source = FileContent(path="bad.py", content=b"hashlib.md5()\n")

    @classmethod
    def rules(cls):
        return (*super().rules(), *bandit_rules(), RootRule(BanditFieldSets))

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
            origin = SingleAddress(directory="", name="target")
        return TargetWithOrigin(target, origin)

    def run_bandit(
        self,
        targets: List[TargetWithOrigin],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
        additional_args: Optional[List[str]] = None,
    ) -> LintResult:
        args = ["--backend-packages2=pants.backend.python.lint.bandit"]
        if config:
            self.create_file(relpath=".bandit", contents=config)
            args.append("--bandit-config=.bandit")
        if passthrough_args:
            args.append(f"--bandit-args={passthrough_args}")
        if skip:
            args.append(f"--bandit-skip")
        if additional_args:
            args.extend(additional_args)
        return self.request_single_product(
            LintResult,
            Params(
                BanditFieldSets(BanditFieldSet.create(tgt) for tgt in targets),
                create_options_bootstrapper(args=args),
            ),
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
        assert "good.py" not in result.stdout
        assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result.stdout

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source]),
            self.make_target_with_origin([self.bad_source]),
        ]
        result = self.run_bandit(targets)
        assert result.exit_code == 1
        assert "good.py" not in result.stdout
        assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result.stdout

    def test_precise_file_args(self) -> None:
        target = self.make_target_with_origin(
            [self.good_source, self.bad_source],
            origin=FilesystemLiteralSpec(self.good_source.path),
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

    def test_3rdparty_plugin(self) -> None:
        target = self.make_target_with_origin(
            [FileContent("bad.py", b"aws_key = 'JalrXUtnFEMI/K7MDENG/bPxRfiCYzEXAMPLEKEY'\n")]
        )
        result = self.run_bandit(
            [target], additional_args=["--bandit-extra-requirements=bandit-aws"]
        )
        assert result.exit_code == 1
        assert "Issue: [C100:hardcoded_aws_key]" in result.stdout
