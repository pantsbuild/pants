# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.docker_build_context import (
    DockerBuildContextRequest,
    create_docker_build_context,
)
from pants.backend.docker.target_types import DockerImage
from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.target_types import PexBinary
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, EMPTY_SNAPSHOT, AddPrefix, Digest, MergeDigests
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionMembership
from pants.testutil.rule_runner import MockGet, run_rule_with_mocks


def test_create_docker_build_context():
    img = DockerImage(address=Address("src/test", target_name="image"), unhydrated_values={})
    pex = PexBinary(
        address=Address("src/test", target_name="bin"),
        unhydrated_values={"entry_point": "src.test.main:main"},
    )
    request = DockerBuildContextRequest(
        address=img.address,
        context_root=".",
    )

    result = run_rule_with_mocks(
        create_docker_build_context,
        rule_args=[request],
        mock_gets=[
            MockGet(
                output_type=TransitiveTargets,
                input_type=TransitiveTargetsRequest,
                mock=lambda _: TransitiveTargets([img], [pex]),
            ),
            MockGet(
                output_type=SourceFiles,
                input_type=SourceFilesRequest,
                mock=lambda _: SourceFiles(
                    snapshot=EMPTY_SNAPSHOT,
                    unrooted_files=tuple(),
                ),
            ),
            MockGet(
                output_type=FieldSetsPerTarget,
                input_type=FieldSetsPerTargetRequest,
                mock=lambda request: FieldSetsPerTarget([[PexBinaryFieldSet.create(pex)]]),
            ),
            MockGet(
                output_type=BuiltPackage,
                input_type=PackageFieldSet,
                mock=lambda _: BuiltPackage(EMPTY_DIGEST, []),
            ),
            MockGet(
                output_type=Digest,
                input_type=AddPrefix,
                mock=lambda _: EMPTY_DIGEST,
            ),
            MockGet(
                output_type=Digest,
                input_type=MergeDigests,
                mock=lambda _: EMPTY_DIGEST,
            ),
        ],
        # need AddPrefix here, since UnionMembership.is_member() throws when called with non
        # registered types
        union_membership=UnionMembership({PackageFieldSet: [PexBinaryFieldSet], AddPrefix: []}),
    )

    assert result.digest == EMPTY_DIGEST
