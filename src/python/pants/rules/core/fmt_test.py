# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from collections import OrderedDict
from pathlib import Path
from typing import List, Type, cast
from unittest.mock import Mock

from pants.base.specs import SingleAddress
from pants.build_graph.address import Address
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest, DirectoriesToMerge, Workspace
from pants.engine.legacy.graph import (
    HydratedTarget,
    HydratedTargetsWithOrigins,
    HydratedTargetWithOrigin,
)
from pants.engine.legacy.structs import (
    JvmBinaryAdaptor,
    PythonTargetAdaptor,
    TargetAdaptor,
    TargetAdaptorWithOrigin,
)
from pants.engine.rules import UnionMembership
from pants.rules.core.fmt import Fmt, FmtResult, LanguageFmtResults, LanguageFormatters, fmt
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase
from pants.util.ordered_set import OrderedSet

PYTHON_FILE = Path("formatted.py")
PYTHON_CONTENT = "print('So Pythonic now!')\n"
PYTHON_DIGEST = Digest(
    fingerprint="ad01e45511ca88c6449a8d86f04226d5763ffe5de82df71f91599a85b04b6982",
    serialized_bytes_length=86,
)

JAVA_FILE = Path("formatted.java")
JAVA_CONTENT = "System.out.println('Yay pretty verbosity!')\n"

MERGED_DIGEST = Digest(
    fingerprint="32a24a86de5c8adf8a5c40f8a3c8dace542089abbeefff3d091f4fedf1df5ba5",
    serialized_bytes_length=174,
)


class MockLanguageFormatters(LanguageFormatters, metaclass=ABCMeta):
    @staticmethod
    @abstractmethod
    def stdout(_: Address) -> str:
        pass

    @property
    def language_fmt_results(self) -> LanguageFmtResults:
        address = self.adaptors_with_origins[0].adaptor.address
        # NB: Due to mocking `await Get[Digest](DirectoriesToMerge), the digest we use here does
        # not matter.
        digest = EMPTY_DIRECTORY_DIGEST
        return LanguageFmtResults(
            (FmtResult(digest=digest, stdout=self.stdout(address), stderr=""),),
            combined_digest=digest,
        )


class PythonFormatters(MockLanguageFormatters):
    @staticmethod
    def belongs_to_language(adaptor_with_origin: TargetAdaptorWithOrigin) -> bool:
        return isinstance(adaptor_with_origin.adaptor, PythonTargetAdaptor)

    @staticmethod
    def stdout(address: Address) -> str:
        return f"Python formatters: formatted {address}"


class JavaFormatters(MockLanguageFormatters):
    @staticmethod
    def belongs_to_language(adaptor_with_origin: TargetAdaptorWithOrigin) -> bool:
        return isinstance(adaptor_with_origin.adaptor, JvmBinaryAdaptor)

    @staticmethod
    def stdout(address: Address) -> str:
        return f"Java formatters: formatted {address}"


class InvalidFormatters(MockLanguageFormatters):
    @staticmethod
    def belongs_to_language(_: TargetAdaptorWithOrigin) -> bool:
        return False

    @staticmethod
    def stdout(address: Address) -> str:
        return f"Invalid formatters: should not have formatted {address}..."


class FmtTest(TestBase):
    @staticmethod
    def make_hydrated_target_with_origin(
        *,
        name: str = "target",
        adaptor_type: Type[TargetAdaptor] = PythonTargetAdaptor,
        include_sources: bool = True,
    ) -> HydratedTargetWithOrigin:
        sources = Mock()
        sources.snapshot = Mock()
        sources.snapshot.files = ("f1",) if include_sources else ()
        address = Address.parse(f"//:{name}")
        ht = HydratedTarget(
            address=address,
            adaptor=adaptor_type(sources=sources, address=address),
            dependencies=(),
        )
        return HydratedTargetWithOrigin(ht, SingleAddress(directory="", name=name))

    def run_fmt_rule(
        self,
        *,
        language_formatters: List[Type[LanguageFormatters]],
        targets: List[HydratedTargetWithOrigin],
        result_digest: Digest,
    ) -> str:
        console = MockConsole(use_colors=False)
        # NB: This ensures that the hardcoded digests can actually be found.
        self.make_snapshot({PYTHON_FILE: PYTHON_CONTENT, JAVA_FILE: JAVA_CONTENT})
        union_membership = UnionMembership(
            OrderedDict({LanguageFormatters: OrderedSet(language_formatters)})
        )
        result: Fmt = run_rule(
            fmt,
            rule_args=[
                console,
                HydratedTargetsWithOrigins(targets),
                Workspace(self.scheduler),
                union_membership,
            ],
            mock_gets=[
                MockGet(
                    product_type=LanguageFmtResults,
                    subject_type=LanguageFormatters,
                    mock=lambda language_formatters: language_formatters.language_fmt_results,
                ),
                MockGet(
                    product_type=Digest,
                    subject_type=DirectoriesToMerge,
                    mock=lambda _: result_digest,
                ),
            ],
            union_membership=union_membership,
        )
        assert result.exit_code == 0
        return cast(str, console.stdout.getvalue())

    def assert_workspace_modified(self, *, python_formatted: bool, java_formatted: bool) -> None:
        python_file = Path(self.build_root, PYTHON_FILE)
        java_file = Path(self.build_root, JAVA_FILE)
        if python_formatted:
            assert python_file.is_file()
            assert python_file.read_text() == PYTHON_CONTENT
        if java_formatted:
            assert java_file.is_file()
            assert java_file.read_text() == JAVA_CONTENT

    def test_empty_target_noops(self) -> None:
        stdout = self.run_fmt_rule(
            language_formatters=[PythonFormatters],
            targets=[self.make_hydrated_target_with_origin(include_sources=False)],
            result_digest=PYTHON_DIGEST,
        )
        assert stdout.strip() == ""
        self.assert_workspace_modified(python_formatted=False, java_formatted=False)

    def test_invalid_target_noops(self) -> None:
        stdout = self.run_fmt_rule(
            language_formatters=[InvalidFormatters],
            targets=[self.make_hydrated_target_with_origin()],
            result_digest=PYTHON_DIGEST,
        )
        assert stdout.strip() == ""
        self.assert_workspace_modified(python_formatted=False, java_formatted=False)

    def test_single_language_with_single_target(self) -> None:
        target_with_origin = self.make_hydrated_target_with_origin()
        stdout = self.run_fmt_rule(
            language_formatters=[PythonFormatters],
            targets=[target_with_origin],
            result_digest=PYTHON_DIGEST,
        )
        assert stdout.strip() == PythonFormatters.stdout(target_with_origin.target.adaptor.address)
        self.assert_workspace_modified(python_formatted=True, java_formatted=False)

    def test_single_language_with_multiple_targets(self) -> None:
        targets_with_origins = [
            self.make_hydrated_target_with_origin(name="t1"),
            self.make_hydrated_target_with_origin(name="t2"),
        ]
        stdout = self.run_fmt_rule(
            language_formatters=[PythonFormatters],
            targets=targets_with_origins,
            result_digest=PYTHON_DIGEST,
        )
        assert stdout.splitlines() == [
            PythonFormatters.stdout(target_with_origin.target.adaptor.address)
            for target_with_origin in targets_with_origins
        ]
        self.assert_workspace_modified(python_formatted=True, java_formatted=False)

    def test_multiple_languages_with_single_targets(self) -> None:
        python_target = self.make_hydrated_target_with_origin(
            name="py", adaptor_type=PythonTargetAdaptor
        )
        java_target = self.make_hydrated_target_with_origin(
            name="java", adaptor_type=JvmBinaryAdaptor
        )
        stdout = self.run_fmt_rule(
            language_formatters=[PythonFormatters, JavaFormatters],
            targets=[python_target, java_target],
            result_digest=MERGED_DIGEST,
        )
        assert stdout.splitlines() == [
            PythonFormatters.stdout(python_target.target.adaptor.address),
            JavaFormatters.stdout(java_target.target.adaptor.address),
        ]
        self.assert_workspace_modified(python_formatted=True, java_formatted=True)

    def test_multiple_languages_with_multiple_targets(self) -> None:
        python_targets = [
            self.make_hydrated_target_with_origin(name="py1", adaptor_type=PythonTargetAdaptor),
            self.make_hydrated_target_with_origin(name="py2", adaptor_type=PythonTargetAdaptor),
        ]
        java_targets = [
            self.make_hydrated_target_with_origin(name="java1", adaptor_type=JvmBinaryAdaptor),
            self.make_hydrated_target_with_origin(name="java2", adaptor_type=JvmBinaryAdaptor),
        ]
        stdout = self.run_fmt_rule(
            language_formatters=[PythonFormatters, JavaFormatters],
            targets=[*python_targets, *java_targets],
            result_digest=MERGED_DIGEST,
        )
        assert stdout.splitlines() == [
            *(
                PythonFormatters.stdout(target_with_origin.target.adaptor.address)
                for target_with_origin in python_targets
            ),
            *(
                JavaFormatters.stdout(target_with_origin.target.adaptor.address)
                for target_with_origin in java_targets
            ),
        ]
        self.assert_workspace_modified(python_formatted=True, java_formatted=True)
