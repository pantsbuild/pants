# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.backend.python.lint.black.rules import BlackRequest
from pants.backend.python.lint.black.rules import rules as black_rules
from pants.backend.python.lint.isort.rules import IsortRequest
from pants.backend.python.lint.isort.rules import rules as isort_rules
from pants.backend.python.lint.python_fmt import PythonFmtTargets, format_python_target
from pants.backend.python.target_types import PythonLibrary
from pants.base.specs import SingleAddress
from pants.core.goals.fmt import LanguageFmtResults
from pants.engine.addresses import Address
from pants.engine.fs import Digest, FileContent, InputFilesContent
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import TargetsWithOrigins, TargetWithOrigin
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.option.util import create_options_bootstrapper


class PythonFmtIntegrationTest(ExternalToolTestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            format_python_target,
            *black_rules(),
            *isort_rules(),
            RootRule(PythonFmtTargets),
            RootRule(BlackRequest),
            RootRule(IsortRequest),
        )

    def run_black_and_isort(
        self, source_files: List[FileContent], *, name: str, extra_args: Optional[List[str]] = None
    ) -> LanguageFmtResults:
        for source_file in source_files:
            self.create_file(source_file.path, source_file.content.decode())
        target = PythonLibrary({}, address=Address.parse(f"test:{name}"))
        origin = SingleAddress(directory="test", name=name)
        targets = PythonFmtTargets(TargetsWithOrigins([TargetWithOrigin(target, origin)]))
        args = [
            "--backend-packages2=['pants.backend.python.lint.black', 'pants.backend.python.lint.isort']",
            *(extra_args or []),
        ]
        results = self.request_single_product(
            LanguageFmtResults, Params(targets, create_options_bootstrapper(args=args)),
        )
        return results

    def get_digest(self, source_files: List[FileContent]) -> Digest:
        return self.request_single_product(Digest, InputFilesContent(source_files))

    def test_multiple_formatters_changing_the_same_file(self) -> None:
        original_source = FileContent(
            "test/target.py", content=b"from animals import dog, cat\n\nprint('hello')\n",
        )
        fixed_source = FileContent(
            "test/target.py", content=b'from animals import cat, dog\n\nprint("hello")\n',
        )
        results = self.run_black_and_isort([original_source], name="same_file")
        assert results.output == self.get_digest([fixed_source])
        assert results.did_change is True

    def test_multiple_formatters_changing_different_files(self) -> None:
        original_sources = [
            FileContent("test/isort.py", content=b"from animals import dog, cat\n"),
            FileContent("test/black.py", content=b"print('hello')\n"),
        ]
        fixed_sources = [
            FileContent("test/isort.py", content=b"from animals import cat, dog\n"),
            FileContent("test/black.py", content=b'print("hello")\n'),
        ]
        results = self.run_black_and_isort(original_sources, name="different_file")
        assert results.output == self.get_digest(fixed_sources)
        assert results.did_change is True

    def test_skipped_formatter(self) -> None:
        """Ensure that a skipped formatter does not interfere with other formatters."""
        original_source = FileContent(
            "test/skipped.py", content=b"from animals import dog, cat\n\nprint('hello')\n",
        )
        fixed_source = FileContent(
            "test/skipped.py", content=b"from animals import cat, dog\n\nprint('hello')\n",
        )
        results = self.run_black_and_isort(
            [original_source], name="skipped", extra_args=["--black-skip"]
        )
        assert results.output == self.get_digest([fixed_source])
        assert results.did_change is True

    def test_no_changes(self) -> None:
        source = FileContent(
            "test/target.py", content=b'from animals import cat, dog\n\nprint("hello")\n',
        )
        results = self.run_black_and_isort([source], name="different_file")
        assert results.output == self.get_digest([source])
        assert results.did_change is False
