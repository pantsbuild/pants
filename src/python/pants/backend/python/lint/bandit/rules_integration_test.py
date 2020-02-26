# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

import pytest

from pants.backend.python.lint.bandit.rules import BanditTargets
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
        return (*super().rules(), *bandit_rules(), RootRule(BanditTargets))

    def run_bandit(
        self,
        source_files: List[FileContent],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        interpreter_constraints: Optional[str] = None,
        skip: bool = False,
        origin: Optional[OriginSpec] = None,
    ) -> LintResult:
        args = ["--backend-packages2=pants.backend.python.lint.bandit"]
        if config:
            # TODO(#9148): The config file exists but parser.py cannot find it
            self.create_file(relpath=".bandit", contents=config)
            args.append("--bandit-config=.bandit")
        if passthrough_args:
            args.append(f"--bandit-args={passthrough_args}")
        if skip:
            args.append(f"--bandit-skip")
        input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
        adaptor = PythonTargetAdaptor(
            sources=EagerFilesetWithSpec("test", {"globs": []}, snapshot=input_snapshot),
            address=Address.parse("test:target"),
            compatibility=[interpreter_constraints] if interpreter_constraints else None,
        )
        if origin is None:
            origin = SingleAddress(directory="test", name="target")
        target = BanditTargets((PythonTargetAdaptorWithOrigin(adaptor, origin),))
        return self.request_single_product(
            LintResult, Params(target, create_options_bootstrapper(args=args)),
        )

    def test_single_passing_source(self) -> None:
        result = self.run_bandit([self.good_source])
        assert result.exit_code == 0
        assert "No issues identified." in result.stdout.strip()

    def test_single_failing_source(self) -> None:
        result = self.run_bandit([self.bad_source])
        assert result.exit_code == 1
        assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result.stdout

    def test_mixed_sources(self) -> None:
        result = self.run_bandit([self.good_source, self.bad_source])
        assert result.exit_code == 1
        assert "test/good.py" not in result.stdout
        assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result.stdout

    def test_precise_file_args(self) -> None:
        file_arg = FilesystemLiteralSpec(self.good_source.path)
        result = self.run_bandit([self.good_source, self.bad_source], origin=file_arg)
        assert result.exit_code == 0
        assert "No issues identified." in result.stdout

    @pytest.mark.skip(reason="#9148: The config file exists but parser.py cannot find it")
    def test_respects_config_file(self) -> None:
        result = self.run_bandit([self.bad_source], config="skips: ['B303']\n")
        assert result.exit_code == 0
        assert "No issues identified." in result.stdout.strip()

    def test_respects_passthrough_args(self) -> None:
        result = self.run_bandit([self.bad_source], passthrough_args="--skip B303")
        assert result.exit_code == 0
        assert "No issues identified." in result.stdout.strip()

    def test_skip(self) -> None:
        result = self.run_bandit([self.bad_source], skip=True)
        assert result == LintResult.noop()
