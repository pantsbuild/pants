# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta, abstractmethod
from pathlib import Path
from typing import Iterable, List, Optional, Type, cast

from pants.base.specs import SingleAddress
from pants.core.goals.fmt import (
    Fmt,
    FmtOptions,
    FmtResult,
    LanguageFmtResults,
    LanguageFmtTargets,
    fmt,
)
from pants.core.util_rules.filter_empty_sources import TargetsWithSources, TargetsWithSourcesRequest
from pants.engine.addresses import Address
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    DirectoriesToMerge,
    FileContent,
    Workspace,
)
from pants.engine.target import Sources, Target, TargetsWithOrigins, TargetWithOrigin
from pants.engine.unions import UnionMembership
from pants.testutil.engine.util import MockConsole, MockGet, create_goal_subsystem, run_rule
from pants.testutil.test_base import TestBase


class FortranSources(Sources):
    pass


class FortranTarget(Target):
    alias = "fortran"
    core_fields = (FortranSources,)


class SmalltalkSources(Sources):
    pass


class SmalltalkTarget(Target):
    alias = "smalltalk"
    core_fields = (SmalltalkSources,)


class InvalidSources(Sources):
    pass


class MockLanguageTargets(LanguageFmtTargets, metaclass=ABCMeta):
    @staticmethod
    @abstractmethod
    def stdout(_: Iterable[Address]) -> str:
        pass

    @property
    def language_fmt_results(self) -> LanguageFmtResults:
        addresses = [
            target_with_origin.target.address for target_with_origin in self.targets_with_origins
        ]
        # NB: Due to mocking `await Get[Digest](DirectoriesToMerge), the digest we use here does
        # not matter.
        digest = EMPTY_DIRECTORY_DIGEST
        return LanguageFmtResults(
            (FmtResult(digest=digest, stdout=self.stdout(addresses), stderr="", did_change=True),),
            combined_digest=digest,
            did_change=True,
        )


class FortranTargets(MockLanguageTargets):
    required_fields = (FortranSources,)

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Fortran targets: {', '.join(str(address) for address in addresses)}"


class SmalltalkTargets(MockLanguageTargets):
    required_fields = (SmalltalkSources,)

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Smalltalk targets: {', '.join(str(address) for address in addresses)}"


class InvalidTargets(MockLanguageTargets):
    required_fields = (InvalidSources,)

    @staticmethod
    def stdout(addresses: Iterable[Address]) -> str:
        return f"Invalid targets: {', '.join(str(address) for address in addresses)}"


class FmtTest(TestBase):
    def setUp(self) -> None:
        super().setUp()
        self.fortran_file = FileContent("formatted.f98", b"READ INPUT TAPE 5\n")
        self.smalltalk_file = FileContent("formatted.st", b"y := self size + super size.')\n")
        self.fortran_digest = self.make_snapshot(
            {self.fortran_file.path: self.fortran_file.content.decode()}
        ).directory_digest
        self.merged_digest = self.make_snapshot(
            {fc.path: fc.content.decode() for fc in (self.fortran_file, self.smalltalk_file)}
        ).directory_digest

    @staticmethod
    def make_target_with_origin(
        address: Optional[Address] = None, *, target_cls: Type[Target] = FortranTarget
    ) -> TargetWithOrigin:
        if address is None:
            address = Address.parse(":tests")
        return TargetWithOrigin(
            target_cls({}, address=address),
            origin=SingleAddress(directory=address.spec_path, name=address.target_name),
        )

    def run_fmt_rule(
        self,
        *,
        language_target_collection_types: List[Type[LanguageFmtTargets]],
        targets: List[TargetWithOrigin],
        result_digest: Digest,
        per_target_caching: bool,
        include_sources: bool = True,
    ) -> str:
        console = MockConsole(use_colors=False)
        union_membership = UnionMembership({LanguageFmtTargets: language_target_collection_types})
        result: Fmt = run_rule(
            fmt,
            rule_args=[
                console,
                TargetsWithOrigins(targets),
                create_goal_subsystem(FmtOptions, per_target_caching=per_target_caching),
                Workspace(self.scheduler),
                union_membership,
            ],
            mock_gets=[
                MockGet(
                    product_type=LanguageFmtResults,
                    subject_type=LanguageFmtTargets,
                    mock=lambda language_targets_collection: language_targets_collection.language_fmt_results,
                ),
                MockGet(
                    product_type=TargetsWithSources,
                    subject_type=TargetsWithSourcesRequest,
                    mock=lambda tgts: TargetsWithSources(tgts if include_sources else ()),
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

    def assert_workspace_modified(
        self, *, fortran_formatted: bool, smalltalk_formatted: bool
    ) -> None:
        fortran_file = Path(self.build_root, self.fortran_file.path)
        smalltalk_file = Path(self.build_root, self.smalltalk_file.path)
        if fortran_formatted:
            assert fortran_file.is_file()
            assert fortran_file.read_text() == self.fortran_file.content.decode()
        if smalltalk_formatted:
            assert smalltalk_file.is_file()
            assert smalltalk_file.read_text() == self.smalltalk_file.content.decode()

    def test_empty_target_noops(self) -> None:
        def assert_noops(*, per_target_caching: bool) -> None:
            stdout = self.run_fmt_rule(
                language_target_collection_types=[FortranTargets],
                targets=[self.make_target_with_origin()],
                result_digest=self.fortran_digest,
                per_target_caching=per_target_caching,
                include_sources=False,
            )
            assert stdout.strip() == ""
            self.assert_workspace_modified(fortran_formatted=False, smalltalk_formatted=False)

        assert_noops(per_target_caching=False)
        assert_noops(per_target_caching=True)

    def test_invalid_target_noops(self) -> None:
        def assert_noops(*, per_target_caching: bool) -> None:
            stdout = self.run_fmt_rule(
                language_target_collection_types=[InvalidTargets],
                targets=[self.make_target_with_origin()],
                result_digest=self.fortran_digest,
                per_target_caching=per_target_caching,
            )
            assert stdout.strip() == ""
            self.assert_workspace_modified(fortran_formatted=False, smalltalk_formatted=False)

        assert_noops(per_target_caching=False)
        assert_noops(per_target_caching=True)

    def test_single_language_with_single_target(self) -> None:
        address = Address.parse(":tests")
        target_with_origin = self.make_target_with_origin(address)

        def assert_expected(*, per_target_caching: bool) -> None:

            stdout = self.run_fmt_rule(
                language_target_collection_types=[FortranTargets],
                targets=[target_with_origin],
                result_digest=self.fortran_digest,
                per_target_caching=per_target_caching,
            )
            assert stdout.strip() == FortranTargets.stdout([address])
            self.assert_workspace_modified(fortran_formatted=True, smalltalk_formatted=False)

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)

    def test_single_language_with_multiple_targets(self) -> None:
        addresses = [Address.parse(":t1"), Address.parse(":t2")]

        def get_stdout(*, per_target_caching: bool) -> str:
            stdout = self.run_fmt_rule(
                language_target_collection_types=[FortranTargets],
                targets=[self.make_target_with_origin(addr) for addr in addresses],
                result_digest=self.fortran_digest,
                per_target_caching=per_target_caching,
            )
            self.assert_workspace_modified(fortran_formatted=True, smalltalk_formatted=False)
            return stdout

        assert get_stdout(per_target_caching=False).strip() == FortranTargets.stdout(addresses)
        assert get_stdout(per_target_caching=True).splitlines() == [
            FortranTargets.stdout([address]) for address in addresses
        ]

    def test_multiple_languages_with_single_targets(self) -> None:
        fortran_address = Address.parse(":fortran")
        smalltalk_address = Address.parse(":smalltalk")

        def assert_expected(*, per_target_caching: bool) -> None:
            stdout = self.run_fmt_rule(
                language_target_collection_types=[FortranTargets, SmalltalkTargets],
                targets=[
                    self.make_target_with_origin(fortran_address, target_cls=FortranTarget),
                    self.make_target_with_origin(smalltalk_address, target_cls=SmalltalkTarget),
                ],
                result_digest=self.merged_digest,
                per_target_caching=per_target_caching,
            )
            assert stdout.splitlines() == [
                FortranTargets.stdout([fortran_address]),
                SmalltalkTargets.stdout([smalltalk_address]),
            ]
            self.assert_workspace_modified(fortran_formatted=True, smalltalk_formatted=True)

        assert_expected(per_target_caching=False)
        assert_expected(per_target_caching=True)

    def test_multiple_languages_with_multiple_targets(self) -> None:
        fortran_addresses = [Address.parse(":py1"), Address.parse(":py2")]
        smalltalk_addresses = [Address.parse(":py1"), Address.parse(":py2")]

        fortran_targets = [
            self.make_target_with_origin(addr, target_cls=FortranTarget)
            for addr in fortran_addresses
        ]
        smalltalk_targets = [
            self.make_target_with_origin(addr, target_cls=SmalltalkTarget)
            for addr in smalltalk_addresses
        ]

        def get_stdout(*, per_target_caching: bool) -> str:
            stdout = self.run_fmt_rule(
                language_target_collection_types=[FortranTargets, SmalltalkTargets],
                targets=[*fortran_targets, *smalltalk_targets],
                result_digest=self.merged_digest,
                per_target_caching=per_target_caching,
            )
            self.assert_workspace_modified(fortran_formatted=True, smalltalk_formatted=True)
            return stdout

        assert get_stdout(per_target_caching=False).splitlines() == [
            FortranTargets.stdout(fortran_addresses),
            SmalltalkTargets.stdout(smalltalk_addresses),
        ]
        assert get_stdout(per_target_caching=True).splitlines() == [
            *(FortranTargets.stdout([address]) for address in fortran_addresses),
            *(SmalltalkTargets.stdout([address]) for address in smalltalk_addresses),
        ]
