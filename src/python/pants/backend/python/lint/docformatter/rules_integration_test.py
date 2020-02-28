# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Tuple

from pants.backend.python.lint.docformatter.rules import DocformatterFormatter
from pants.backend.python.lint.docformatter.rules import rules as docformatter_rules
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


class DocformatterIntegrationTest(TestBase):

    good_source = FileContent(path="test/good.py", content=b'"""Good docstring."""\n')
    bad_source = FileContent(path="test/bad.py", content=b'"""Oops, missing a period"""\n')
    fixed_bad_source = FileContent(path="test/bad.py", content=b'"""Oops, missing a period."""\n')

    @classmethod
    def rules(cls):
        return (*super().rules(), *docformatter_rules(), RootRule(DocformatterFormatter))

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

    def run_docformatter(
        self,
        targets: List[TargetAdaptorWithOrigin],
        *,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
    ) -> Tuple[LintResult, FmtResult]:
        args = ["--backend-packages2=pants.backend.python.lint.docformatter"]
        if passthrough_args:
            args.append(f"--docformatter-args='{passthrough_args}'")
        if skip:
            args.append(f"--docformatter-skip")
        options_bootstrapper = create_options_bootstrapper(args=args)
        lint_result = self.request_single_product(
            LintResult, Params(DocformatterFormatter(tuple(targets)), options_bootstrapper)
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
                DocformatterFormatter(tuple(targets), prior_formatter_result=input_snapshot),
                options_bootstrapper,
            ),
        )
        return lint_result, fmt_result

    def get_digest(self, source_files: List[FileContent]) -> Digest:
        return self.request_single_product(Digest, InputFilesContent(source_files))

    def test_passing_source(self) -> None:
        target = self.make_target_with_origin([self.good_source])
        lint_result, fmt_result = self.run_docformatter([target])
        assert lint_result == LintResult.noop()
        assert fmt_result.digest == self.get_digest([self.good_source])

    def test_failing_source(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        lint_result, fmt_result = self.run_docformatter([target])
        assert lint_result.exit_code == 3
        assert lint_result.stderr.strip() == self.bad_source.path
        assert fmt_result.digest == self.get_digest([self.fixed_bad_source])

    def test_mixed_sources(self) -> None:
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        lint_result, fmt_result = self.run_docformatter([target])
        assert lint_result.exit_code == 3
        assert lint_result.stderr.strip() == self.bad_source.path
        assert fmt_result.digest == self.get_digest([self.good_source, self.fixed_bad_source])

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source]),
            self.make_target_with_origin([self.bad_source]),
        ]
        lint_result, fmt_result = self.run_docformatter(targets)
        assert lint_result.exit_code == 3
        assert lint_result.stderr.strip() == self.bad_source.path
        assert fmt_result.digest == self.get_digest([self.good_source, self.fixed_bad_source])

    def test_precise_file_args(self) -> None:
        target = self.make_target_with_origin(
            [self.good_source, self.bad_source], origin=FilesystemLiteralSpec(self.good_source.path)
        )
        lint_result, fmt_result = self.run_docformatter([target])
        assert lint_result == LintResult.noop()
        assert fmt_result.digest == self.get_digest([self.good_source, self.bad_source])

    def test_respects_passthrough_args(self) -> None:
        needs_config = FileContent(
            path="test/config.py",
            content=b'"""\nOne line docstring acting like it\'s multiline.\n"""\n',
        )
        target = self.make_target_with_origin([needs_config])
        lint_result, fmt_result = self.run_docformatter(
            [target], passthrough_args="--make-summary-multi-line"
        )
        assert lint_result == LintResult.noop()
        assert fmt_result.digest == self.get_digest([needs_config])

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        lint_result, fmt_result = self.run_docformatter([target], skip=True)
        assert lint_result == LintResult.noop()
        assert fmt_result == FmtResult.noop()
