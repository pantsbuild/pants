# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.backend.python.lint.black.rules import BlackFormatter
from pants.backend.python.lint.black.rules import rules as black_rules
from pants.backend.python.lint.isort.rules import IsortFormatter
from pants.backend.python.lint.isort.rules import rules as isort_rules
from pants.backend.python.lint.python_formatter import PythonFormatters, format_python_target
from pants.backend.python.rules.hermetic_pex import rules as hermetic_pex_rules
from pants.base.specs import SingleAddress
from pants.build_graph.address import Address
from pants.engine.fs import Digest, FileContent, InputFilesContent, Snapshot
from pants.engine.legacy.structs import TargetAdaptor, TargetAdaptorWithOrigin
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.fmt import LanguageFmtResults
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PythonFormatterIntegrationTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            format_python_target,
            *black_rules(),
            *hermetic_pex_rules(),
            *isort_rules(),
            RootRule(PythonFormatters),
            RootRule(BlackFormatter),
            RootRule(IsortFormatter),
        )

    def run_black_and_isort(
        self, source_files: List[FileContent], *, extra_args: Optional[List[str]] = None
    ) -> LanguageFmtResults:
        input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
        adaptor = TargetAdaptor(
            sources=EagerFilesetWithSpec("test", {"globs": []}, snapshot=input_snapshot),
            address=Address.parse("test:target"),
        )
        origin = SingleAddress(directory="test", name="target")
        formatters = PythonFormatters((TargetAdaptorWithOrigin(adaptor, origin),))
        args = [
            "--backend-packages2=['pants.backend.python.lint.black', 'pants.backend.python.lint.isort']",
            *(extra_args or []),
        ]
        results = self.request_single_product(
            LanguageFmtResults, Params(formatters, create_options_bootstrapper(args=args)),
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
        results = self.run_black_and_isort([original_source])
        assert results.combined_digest == self.get_digest([fixed_source])

    def test_multiple_formatters_changing_different_files(self) -> None:
        original_sources = [
            FileContent("test/isort.py", content=b"from animals import dog, cat\n"),
            FileContent("test/black.py", content=b"print('hello')\n"),
        ]
        fixed_sources = [
            FileContent("test/isort.py", content=b"from animals import cat, dog\n"),
            FileContent("test/black.py", content=b'print("hello")\n'),
        ]
        results = self.run_black_and_isort(original_sources)
        assert results.combined_digest == self.get_digest(fixed_sources)

    def test_skipped_formatter(self) -> None:
        """Ensure that a skipped formatter does not interfere with other formatters."""
        original_source = FileContent(
            "test/target.py", content=b"from animals import dog, cat\n\nprint('hello')\n",
        )
        fixed_source = FileContent(
            "test/target.py", content=b"from animals import cat, dog\n\nprint('hello')\n",
        )
        results = self.run_black_and_isort([original_source], extra_args=["--black-skip"])
        assert results.combined_digest == self.get_digest([fixed_source])
