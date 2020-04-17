# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Tuple

from pants.backend.python.lint.isort.rules import IsortConfiguration, IsortConfigurations
from pants.backend.python.lint.isort.rules import rules as isort_rules
from pants.backend.python.rules.targets import PythonLibrary
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.build_graph.address import Address
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.engine.fs import Digest, FileContent, InputFilesContent
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import TargetWithOrigin
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class IsortIntegrationTest(TestBase):

    good_source = FileContent(path="good.py", content=b"from animals import cat, dog\n")
    bad_source = FileContent(path="bad.py", content=b"from colors import green, blue\n")
    fixed_bad_source = FileContent(path="bad.py", content=b"from colors import blue, green\n")
    # Note the as import. Isort by default keeps as imports on a new line, so this wouldn't be
    # reformatted by default. If we set the config/CLI args correctly, isort will combine the two
    # imports into one line.
    needs_config_source = FileContent(
        path="needs_config.py",
        content=b"from colors import blue\nfrom colors import green as verde\n",
    )
    fixed_needs_config_source = FileContent(
        path="needs_config.py", content=b"from colors import blue, green as verde\n"
    )

    @classmethod
    def rules(cls):
        return (*super().rules(), *isort_rules(), RootRule(IsortConfigurations))

    def make_target_with_origin(
        self, source_files: List[FileContent], *, origin: Optional[OriginSpec] = None,
    ) -> TargetWithOrigin:
        for source_file in source_files:
            self.create_file(f"{source_file.path}", source_file.content.decode())
        target = PythonLibrary({}, address=Address.parse(":target"))
        if origin is None:
            origin = SingleAddress(directory="", name="target")
        return TargetWithOrigin(target, origin)

    def run_isort(
        self,
        targets: List[TargetWithOrigin],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
    ) -> Tuple[LintResult, FmtResult]:
        args = ["--backend-packages2=pants.backend.python.lint.isort"]
        if config is not None:
            self.create_file(relpath=".isort.cfg", contents=config)
            args.append("--isort-config=.isort.cfg")
        if passthrough_args:
            args.append(f"--isort-args='{passthrough_args}'")
        if skip:
            args.append(f"--isort-skip")
        options_bootstrapper = create_options_bootstrapper(args=args)
        configs = [IsortConfiguration.create(tgt) for tgt in targets]
        lint_result = self.request_single_product(
            LintResult, Params(IsortConfigurations(configs), options_bootstrapper)
        )
        input_snapshot = self.request_single_product(
            SourceFiles,
            Params(
                AllSourceFilesRequest(config.sources for config in configs), options_bootstrapper
            ),
        )
        fmt_result = self.request_single_product(
            FmtResult,
            Params(
                IsortConfigurations(configs, prior_formatter_result=input_snapshot),
                options_bootstrapper,
            ),
        )
        return lint_result, fmt_result

    def get_digest(self, source_files: List[FileContent]) -> Digest:
        return self.request_single_product(Digest, InputFilesContent(source_files))

    def test_passing_source(self) -> None:
        target = self.make_target_with_origin([self.good_source])
        lint_result, fmt_result = self.run_isort([target])
        assert lint_result.exit_code == 0
        assert lint_result.stdout == ""
        assert fmt_result.stdout == ""
        assert fmt_result.digest == self.get_digest([self.good_source])

    def test_failing_source(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        lint_result, fmt_result = self.run_isort([target])
        assert lint_result.exit_code == 1
        assert "bad.py Imports are incorrectly sorted" in lint_result.stdout
        assert "Fixing" in fmt_result.stdout
        assert "bad.py" in fmt_result.stdout
        assert fmt_result.digest == self.get_digest([self.fixed_bad_source])

    def test_mixed_sources(self) -> None:
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        lint_result, fmt_result = self.run_isort([target])
        assert lint_result.exit_code == 1
        assert "bad.py Imports are incorrectly sorted" in lint_result.stdout
        assert "good.py" not in lint_result.stdout
        assert "Fixing" in fmt_result.stdout and "bad.py" in fmt_result.stdout
        assert "good.py" not in fmt_result.stdout
        assert fmt_result.digest == self.get_digest([self.good_source, self.fixed_bad_source])

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source]),
            self.make_target_with_origin([self.bad_source]),
        ]
        lint_result, fmt_result = self.run_isort(targets)
        assert lint_result.exit_code == 1
        assert "bad.py Imports are incorrectly sorted" in lint_result.stdout
        assert "good.py" not in lint_result.stdout
        assert "Fixing" in fmt_result.stdout and "bad.py" in fmt_result.stdout
        assert "good.py" not in fmt_result.stdout
        assert fmt_result.digest == self.get_digest([self.good_source, self.fixed_bad_source])

    def test_precise_file_args(self) -> None:
        target = self.make_target_with_origin(
            [self.good_source, self.bad_source], origin=FilesystemLiteralSpec(self.good_source.path)
        )
        lint_result, fmt_result = self.run_isort([target])
        assert lint_result.exit_code == 0
        assert lint_result.stdout == ""
        assert fmt_result.stdout == ""
        assert fmt_result.digest == self.get_digest([self.good_source, self.bad_source])

    def test_respects_config_file(self) -> None:
        target = self.make_target_with_origin([self.needs_config_source])
        lint_result, fmt_result = self.run_isort(
            [target], config="[settings]\ncombine_as_imports=True\n",
        )
        assert lint_result.exit_code == 1
        assert "config.py Imports are incorrectly sorted" in lint_result.stdout
        assert "Fixing" in fmt_result.stdout
        assert "config.py" in fmt_result.stdout
        assert fmt_result.digest == self.get_digest([self.fixed_needs_config_source])

    def test_respects_passthrough_args(self) -> None:
        target = self.make_target_with_origin([self.needs_config_source])
        lint_result, fmt_result = self.run_isort([target], passthrough_args="--combine-as",)
        assert lint_result.exit_code == 1
        assert "config.py Imports are incorrectly sorted" in lint_result.stdout
        assert "Fixing" in fmt_result.stdout
        assert "config.py" in fmt_result.stdout
        assert fmt_result.digest == self.get_digest([self.fixed_needs_config_source])

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        lint_result, fmt_result = self.run_isort([target], skip=True)
        assert lint_result == LintResult.noop()
        assert fmt_result == FmtResult.noop()
