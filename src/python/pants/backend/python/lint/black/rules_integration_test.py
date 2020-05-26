# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Tuple

from pants.backend.python.lint.black.rules import BlackFieldSet, BlackRequest
from pants.backend.python.lint.black.rules import rules as black_rules
from pants.backend.python.target_types import PythonLibrary
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResults
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.engine.addresses import Address
from pants.engine.fs import Digest, FileContent, InputFilesContent
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import TargetWithOrigin
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.option.util import create_options_bootstrapper


class BlackIntegrationTest(ExternalToolTestBase):

    good_source = FileContent(path="good.py", content=b'animal = "Koala"\n')
    bad_source = FileContent(path="bad.py", content=b'name=    "Anakin"\n')
    fixed_bad_source = FileContent(path="bad.py", content=b'name = "Anakin"\n')
    # Note the single quotes, which Black does not like by default. To get Black to pass, it will
    # need to successfully read our config/CLI args.
    needs_config_source = FileContent(path="needs_config.py", content=b"animal = 'Koala'\n")

    @classmethod
    def rules(cls):
        return (*super().rules(), *black_rules(), RootRule(BlackRequest))

    def make_target_with_origin(
        self, source_files: List[FileContent], *, origin: Optional[OriginSpec] = None,
    ) -> TargetWithOrigin:
        for source_file in source_files:
            self.create_file(f"{source_file.path}", source_file.content.decode())
        target = PythonLibrary({}, address=Address.parse(":target"))
        if origin is None:
            origin = SingleAddress(directory="", name="target")
        return TargetWithOrigin(target, origin)

    def run_black(
        self,
        targets: List[TargetWithOrigin],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
    ) -> Tuple[LintResults, FmtResult]:
        args = ["--backend-packages2=pants.backend.python.lint.black"]
        if config is not None:
            self.create_file(relpath="pyproject.toml", contents=config)
            args.append("--black-config=pyproject.toml")
        if passthrough_args:
            args.append(f"--black-args='{passthrough_args}'")
        if skip:
            args.append("--black-skip")
        options_bootstrapper = create_options_bootstrapper(args=args)
        field_sets = [BlackFieldSet.create(tgt) for tgt in targets]
        lint_results = self.request_single_product(
            LintResults, Params(BlackRequest(field_sets), options_bootstrapper)
        )
        input_sources = self.request_single_product(
            SourceFiles,
            Params(
                AllSourceFilesRequest(field_set.sources for field_set in field_sets),
                options_bootstrapper,
            ),
        )
        fmt_result = self.request_single_product(
            FmtResult,
            Params(
                BlackRequest(field_sets, prior_formatter_result=input_sources.snapshot),
                options_bootstrapper,
            ),
        )
        return lint_results, fmt_result

    def get_digest(self, source_files: List[FileContent]) -> Digest:
        return self.request_single_product(Digest, InputFilesContent(source_files))

    def test_passing_source(self) -> None:
        target = self.make_target_with_origin([self.good_source])
        lint_results, fmt_result = self.run_black([target])
        assert len(lint_results) == 1
        assert lint_results[0].exit_code == 0
        assert "1 file would be left unchanged" in lint_results[0].stderr
        assert "1 file left unchanged" in fmt_result.stderr
        assert fmt_result.output == self.get_digest([self.good_source])
        assert fmt_result.did_change is False

    def test_failing_source(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        lint_results, fmt_result = self.run_black([target])
        assert len(lint_results) == 1
        assert lint_results[0].exit_code == 1
        assert "1 file would be reformatted" in lint_results[0].stderr
        assert "1 file reformatted" in fmt_result.stderr
        assert fmt_result.output == self.get_digest([self.fixed_bad_source])
        assert fmt_result.did_change is True

    def test_mixed_sources(self) -> None:
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        lint_results, fmt_result = self.run_black([target])
        assert len(lint_results) == 1
        assert lint_results[0].exit_code == 1
        assert (
            "1 file would be reformatted, 1 file would be left unchanged" in lint_results[0].stderr
        )
        assert "1 file reformatted, 1 file left unchanged", fmt_result.stderr
        assert fmt_result.output == self.get_digest([self.good_source, self.fixed_bad_source])
        assert fmt_result.did_change is True

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source]),
            self.make_target_with_origin([self.bad_source]),
        ]
        lint_results, fmt_result = self.run_black(targets)
        assert len(lint_results) == 1
        assert lint_results[0].exit_code == 1
        assert (
            "1 file would be reformatted, 1 file would be left unchanged" in lint_results[0].stderr
        )
        assert "1 file reformatted, 1 file left unchanged" in fmt_result.stderr
        assert fmt_result.output == self.get_digest([self.good_source, self.fixed_bad_source])
        assert fmt_result.did_change is True

    def test_precise_file_args(self) -> None:
        target = self.make_target_with_origin(
            [self.good_source, self.bad_source], origin=FilesystemLiteralSpec(self.good_source.path)
        )
        lint_results, fmt_result = self.run_black([target])
        assert len(lint_results) == 1
        assert lint_results[0].exit_code == 0
        assert "1 file would be left unchanged" in lint_results[0].stderr
        assert "1 file left unchanged" in fmt_result.stderr
        assert fmt_result.output == self.get_digest([self.good_source, self.bad_source])
        assert fmt_result.did_change is False

    def test_respects_config_file(self) -> None:
        target = self.make_target_with_origin([self.needs_config_source])
        lint_results, fmt_result = self.run_black(
            [target], config="[tool.black]\nskip-string-normalization = 'true'\n"
        )
        assert len(lint_results) == 1
        assert lint_results[0].exit_code == 0
        assert "1 file would be left unchanged" in lint_results[0].stderr
        assert "1 file left unchanged" in fmt_result.stderr
        assert fmt_result.output == self.get_digest([self.needs_config_source])
        assert fmt_result.did_change is False

    def test_respects_passthrough_args(self) -> None:
        target = self.make_target_with_origin([self.needs_config_source])
        lint_results, fmt_result = self.run_black(
            [target], passthrough_args="--skip-string-normalization",
        )
        assert len(lint_results) == 1
        assert lint_results[0].exit_code == 0
        assert "1 file would be left unchanged" in lint_results[0].stderr
        assert "1 file left unchanged" in fmt_result.stderr
        assert fmt_result.output == self.get_digest([self.needs_config_source])
        assert fmt_result.did_change is False

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        lint_results, fmt_result = self.run_black([target], skip=True)
        assert not lint_results
        assert fmt_result == FmtResult.noop()
        assert fmt_result.did_change is False
