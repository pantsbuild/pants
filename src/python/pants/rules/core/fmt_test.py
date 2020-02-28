# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from typing import List, Tuple, Type

from pants.base.specs import SingleAddress
from pants.build_graph.address import Address
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    DirectoriesToMerge,
    FileContent,
    InputFilesContent,
    Snapshot,
    Workspace,
)
from pants.engine.legacy.graph import (
    HydratedTarget,
    HydratedTargetsWithOrigins,
    HydratedTargetWithOrigin,
)
from pants.engine.legacy.structs import (
    JvmAppAdaptor,
    PythonTargetAdaptor,
    PythonTargetAdaptorWithOrigin,
    TargetAdaptor,
)
from pants.engine.rules import UnionMembership
from pants.rules.core.fmt import AggregatedFmtResults, Fmt, FmtResult, FormatTarget, fmt
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase


class FmtTest(TestBase):

    formatted_file = Path("formatted.txt")
    formatted_content = "I'm so pretty now!\n"

    @staticmethod
    def make_hydrated_target_with_origin(
        *,
        name: str = "target",
        adaptor_type: Type[TargetAdaptor] = PythonTargetAdaptor,
        include_sources: bool = True,
    ) -> HydratedTargetWithOrigin:
        mocked_snapshot = Snapshot(
            # TODO: this is not robust to set as an empty digest. Add a test util that provides
            #  some premade snapshots and possibly a generalized make_hydrated_target_with_origin function.
            directory_digest=EMPTY_DIRECTORY_DIGEST,
            files=tuple(["formatted.txt", "fake.txt"] if include_sources else []),
            dirs=(),
        )
        address = Address.parse(f"src/python:{name}")
        ht = HydratedTarget(
            address=address,
            adaptor=adaptor_type(
                sources=EagerFilesetWithSpec("src/python", {"globs": []}, snapshot=mocked_snapshot),
                name=name,
                address=address,
            ),
            dependencies=(),
        )
        return HydratedTargetWithOrigin(ht, SingleAddress(directory="src/python", name=name))

    def run_fmt_rule(self, *, targets: List[HydratedTargetWithOrigin]) -> Tuple[int, str]:
        result_digest = self.request_single_product(
            Digest,
            InputFilesContent(
                [
                    FileContent(
                        path=self.formatted_file.as_posix(), content=self.formatted_content.encode()
                    )
                ]
            ),
        )
        console = MockConsole(use_colors=False)
        union_membership = UnionMembership({FormatTarget: [PythonTargetAdaptorWithOrigin]})
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
                    product_type=AggregatedFmtResults,
                    subject_type=FormatTarget,
                    mock=lambda adaptor_with_origin: AggregatedFmtResults(
                        (
                            FmtResult(
                                digest=result_digest,
                                stdout=f"Formatted `{adaptor_with_origin.adaptor.name}`",
                                stderr="",
                            ),
                        ),
                        combined_digest=result_digest,
                    ),
                ),
                MockGet(
                    product_type=Digest,
                    subject_type=DirectoriesToMerge,
                    mock=lambda _: result_digest,
                ),
            ],
            union_membership=union_membership,
        )
        return result.exit_code, console.stdout.getvalue()

    def assert_workspace_modified(self, *, modified: bool = True) -> None:
        formatted_file = Path(self.build_root, self.formatted_file)
        if not modified:
            assert not formatted_file.is_file()
            return
        assert formatted_file.is_file()
        assert formatted_file.read_text() == self.formatted_content

    def test_non_union_member_noops(self) -> None:
        exit_code, stdout = self.run_fmt_rule(
            targets=[self.make_hydrated_target_with_origin(adaptor_type=JvmAppAdaptor)]
        )
        assert exit_code == 0
        assert stdout.strip() == ""
        self.assert_workspace_modified(modified=False)

    def test_empty_target_noops(self) -> None:
        exit_code, stdout = self.run_fmt_rule(
            targets=[self.make_hydrated_target_with_origin(include_sources=False)]
        )
        assert exit_code == 0
        assert stdout.strip() == ""
        self.assert_workspace_modified(modified=False)

    def test_single_target(self) -> None:
        exit_code, stdout = self.run_fmt_rule(targets=[self.make_hydrated_target_with_origin()])
        assert exit_code == 0
        assert stdout.strip() == "Formatted `target`"
        self.assert_workspace_modified()

    def test_multiple_targets(self) -> None:
        # NB: we do not test the case where AggregatedFmtResults have conflicting changes, as that
        # logic is handled by DirectoriesToMerge and is avoided by each language having its own
        # aggregator rule.
        exit_code, stdout = self.run_fmt_rule(
            targets=[
                self.make_hydrated_target_with_origin(name="t1"),
                self.make_hydrated_target_with_origin(name="t2"),
            ]
        )
        assert exit_code == 0
        assert stdout.splitlines() == ["Formatted `t1`", "Formatted `t2`"]
        self.assert_workspace_modified()
