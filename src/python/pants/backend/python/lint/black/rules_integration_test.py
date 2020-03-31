# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Tuple

from pants.backend.python.lint.black.rules import BlackFormatter
from pants.backend.python.lint.black.rules import rules as black_rules
from pants.backend.python.rules.hermetic_pex import rules as hermetic_pex_rules
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.build_graph.address import Address
from pants.engine.fs import Digest, DirectoriesToMerge, FileContent, InputFilesContent, Snapshot
from pants.engine.legacy.structs import TargetAdaptor, TargetAdaptorWithOrigin
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.fmt import FmtResult
from pants.rules.core.lint import LintResult
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class BlackIntegrationTest(TestBase):

    good_source = FileContent(path="test/good.py", content=b'animal = "Koala"\n')
    bad_source = FileContent(path="test/bad.py", content=b'name=    "Anakin"\n')
    fixed_bad_source = FileContent(path="test/bad.py", content=b'name = "Anakin"\n')
    # Note the single quotes, which Black does not like by default. To get Black to pass, it will
    # need to successfully read our config/CLI args.
    needs_config_source = FileContent(path="test/config.py", content=b"animal = 'Koala'\n")

    @classmethod
    def rules(cls):
        return (*super().rules(), *black_rules(), *hermetic_pex_rules(), RootRule(BlackFormatter))

    def make_target_with_origin(
        self, source_files: List[FileContent], *, origin: Optional[OriginSpec] = None,
    ) -> TargetAdaptorWithOrigin:
        input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
        adaptor = TargetAdaptor(
            sources=EagerFilesetWithSpec("test", {"globs": []}, snapshot=input_snapshot),
            address=Address.parse("test:target"),
        )
        if origin is None:
            origin = SingleAddress(directory="test", name="target")
        return TargetAdaptorWithOrigin(adaptor, origin)

    def run_black(
        self,
        targets: List[TargetAdaptorWithOrigin],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
    ) -> Tuple[LintResult, FmtResult]:
        args = ["--backend-packages2=pants.backend.python.lint.black"]
        if config is not None:
            self.create_file(relpath="pyproject.toml", contents=config)
            args.append("--black-config=pyproject.toml")
        if passthrough_args:
            args.append(f"--black-args='{passthrough_args}'")
        if skip:
            args.append(f"--black-skip")
        options_bootstrapper = create_options_bootstrapper(args=args)
        lint_result = self.request_single_product(
            LintResult, Params(BlackFormatter(tuple(targets)), options_bootstrapper)
        )
        input_snapshot = self.request_single_product(
            Snapshot,
            DirectoriesToMerge(
                tuple(target.adaptor.sources.snapshot.directory_digest for target in targets)
            ),
        )
        fmt_result = self.request_single_product(
            FmtResult,
            Params(
                BlackFormatter(tuple(targets), prior_formatter_result=input_snapshot),
                options_bootstrapper,
            ),
        )
        return lint_result, fmt_result

    def get_digest(self, source_files: List[FileContent]) -> Digest:
        return self.request_single_product(Digest, InputFilesContent(source_files))

    def test_passing_source(self) -> None:
        target = self.make_target_with_origin([self.good_source])
        lint_result, fmt_result = self.run_black([target])
        assert lint_result.exit_code == 0
        assert "1 file would be left unchanged" in lint_result.stderr
        assert "1 file left unchanged" in fmt_result.stderr
        assert fmt_result.digest == self.get_digest([self.good_source])

    def test_failing_source(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        lint_result, fmt_result = self.run_black([target])
        assert lint_result.exit_code == 1
        assert "1 file would be reformatted" in lint_result.stderr
        assert "1 file reformatted" in fmt_result.stderr
        assert fmt_result.digest == self.get_digest([self.fixed_bad_source])

    def test_mixed_sources(self) -> None:
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        lint_result, fmt_result = self.run_black([target])
        assert lint_result.exit_code == 1
        assert "1 file would be reformatted, 1 file would be left unchanged" in lint_result.stderr
        assert "1 file reformatted, 1 file left unchanged", fmt_result.stderr
        assert fmt_result.digest == self.get_digest([self.good_source, self.fixed_bad_source])

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source]),
            self.make_target_with_origin([self.bad_source]),
        ]
        lint_result, fmt_result = self.run_black(targets)
        assert lint_result.exit_code == 1
        assert "1 file would be reformatted, 1 file would be left unchanged" in lint_result.stderr
        assert "1 file reformatted, 1 file left unchanged" in fmt_result.stderr
        assert fmt_result.digest == self.get_digest([self.good_source, self.fixed_bad_source])

    def test_precise_file_args(self) -> None:
        target = self.make_target_with_origin(
            [self.good_source, self.bad_source], origin=FilesystemLiteralSpec(self.good_source.path)
        )
        lint_result, fmt_result = self.run_black([target])
        assert lint_result.exit_code == 0
        assert "1 file would be left unchanged" in lint_result.stderr
        assert "1 file left unchanged" in fmt_result.stderr
        assert fmt_result.digest == self.get_digest([self.good_source, self.bad_source])

    def test_respects_config_file(self) -> None:
        target = self.make_target_with_origin([self.needs_config_source])
        lint_result, fmt_result = self.run_black(
            [target], config="[tool.black]\nskip-string-normalization = 'true'\n"
        )
        assert lint_result.exit_code == 0
        assert "1 file would be left unchanged" in lint_result.stderr
        assert "1 file left unchanged" in fmt_result.stderr
        assert fmt_result.digest == self.get_digest([self.needs_config_source])

    def test_respects_passthrough_args(self) -> None:
        target = self.make_target_with_origin([self.needs_config_source])
        lint_result, fmt_result = self.run_black(
            [target], passthrough_args="--skip-string-normalization",
        )
        assert lint_result.exit_code == 0
        assert "1 file would be left unchanged" in lint_result.stderr
        assert "1 file left unchanged" in fmt_result.stderr
        assert fmt_result.digest == self.get_digest([self.needs_config_source])

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        lint_result, fmt_result = self.run_black([target], skip=True)
        assert lint_result == LintResult.noop()
        assert fmt_result == FmtResult.noop()
