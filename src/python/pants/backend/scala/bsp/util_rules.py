from __future__ import annotations

from dataclasses import dataclass

from pants.backend.scala.bsp.spec import ScalaBuildTarget, ScalaPlatform
from pants.backend.scala.subsystems.scala import ScalaSubsystem
from pants.base.build_root import BuildRoot
from pants.engine.internals.native_engine import Digest, AddPrefix, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.rules import rule, collect_rules
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField


@dataclass(frozen=True)
class MaterializeScalaRuntimeJarsRequest:
    scala_version: str


@dataclass(frozen=True)
class MaterializeScalaRuntimeJarsResult:
    content: Snapshot


@rule
async def materialize_scala_runtime_jars(
    request: MaterializeScalaRuntimeJarsRequest,
) -> MaterializeScalaRuntimeJarsResult:
    tool_classpath = await Get(
        ToolClasspath,
        ToolClasspathRequest(
            artifact_requirements=ArtifactRequirements.from_coordinates(
                [
                    Coordinate(
                        group="org.scala-lang",
                        artifact="scala-compiler",
                        version=request.scala_version,
                    ),
                    Coordinate(
                        group="org.scala-lang",
                        artifact="scala-library",
                        version=request.scala_version,
                    ),
                ]
            ),
        ),
    )

    materialized_classpath_digest = await Get(
        Digest,
        AddPrefix(tool_classpath.content.digest, f"jvm/scala-runtime/{request.scala_version}"),
    )
    materialized_classpath = await Get(Snapshot, Digest, materialized_classpath_digest)
    return MaterializeScalaRuntimeJarsResult(materialized_classpath)


@dataclass(frozen=True)
class ScalaBuildTargetInfo:
    btgt: ScalaBuildTarget
    digest: Digest


@rule
async def make_scala_build_target(
    resolve_field: JvmResolveField,
    jvm: JvmSubsystem,
    scala: ScalaSubsystem,
    build_root: BuildRoot,
) -> ScalaBuildTargetInfo:
    resolve = resolve_field.normalized_value(jvm)
    scala_version = scala.version_for_resolve(resolve)
    scala_runtime = await Get(MaterializeScalaRuntimeJarsResult, MaterializeScalaRuntimeJarsRequest(scala_version))
    scala_jar_uris = tuple(
        build_root.pathlib_path.joinpath(".pants.d/bsp").joinpath(p).as_uri()
        for p in scala_runtime.content.files
    )
    return ScalaBuildTargetInfo(
        btgt=ScalaBuildTarget(
            scala_organization="org.scala-lang",
            scala_version=scala_version,
            scala_binary_version=".".join(scala_version.split(".")[0:2]),
            platform=ScalaPlatform.JVM,
            jars=scala_jar_uris,
        ),
        digest=scala_runtime.content.digest,
    )


def rules():
    return collect_rules()