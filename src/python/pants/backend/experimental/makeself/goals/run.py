import os

from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunRequest
from pants.engine.process import Process
from pants.engine.rules import Get, collect_rules, rule
from pants_backend_makeself.goals.package import MakeselfArchiveFieldSet
from pants_backend_makeself.makeself import RunMakeselfArchive


@rule
async def create_makeself_archive_run_request(field_set: MakeselfArchiveFieldSet) -> RunRequest:
    package = await Get(BuiltPackage, PackageFieldSet, field_set)

    exe = package.artifacts[0].relpath
    assert exe is not None, package
    process = await Get(
        Process,
        RunMakeselfArchive(
            exe=exe,
            input_digest=package.digest,
            description="Run makeself archive",
        ),
    )

    return RunRequest(
        digest=process.input_digest,
        args=(os.path.join("{chroot}", process.argv[0]),) + process.argv[1:],
        extra_env=process.env,
        immutable_input_digests=process.immutable_input_digests,
    )


def rules():
    return collect_rules()
