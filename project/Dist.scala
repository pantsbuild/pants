/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

import sbt._
import sbt.Keys._
import sbt.Project.Initialize

object Dist {
  val distBase = SettingKey[File]("dist-base")
  val distLibs = TaskKey[Seq[(File, String)]]("dist-libs")
  val distTarget = SettingKey[File]("dist-target")
  val create = TaskKey[File]("create", "Create a distribution.")
  val packageTgz = TaskKey[File]("package-tgz", "Create a gzipped tar of the dist.")

  lazy val settings: Seq[Setting[_]] = Seq(
    distBase <<= sourceDirectory / "dist",
    distLibs <<= projectLibs(zincProject),
    distTarget <<= (crossTarget, version) { (dir, v) => dir / ("zinc-" + v) },
    create <<= (distBase, distLibs, distTarget, streams) map createDist,
    packageTgz <<= (create, crossTarget, streams) map createTgz,
    Keys.`package` <<= packageTgz,
    artifact in packageTgz := Artifact("zinc", "tgz", "tgz"),
    publishMavenStyle := true,
    publishArtifact in makePom := false,
    publishArtifact := false,
    publishTo := Some("zinc repo" at "http://repo.typesafe.com/typesafe/zinc"),
    credentials := Seq(Credentials(Path.userHome / ".ivy2" / "typesafe-credentials"))
  ) ++ addArtifact(artifact in packageTgz, packageTgz)

  def zincProject: ProjectReference = LocalProject(ZincBuild.zinc.id)

  def projectLibs(project: ProjectReference): Initialize[Task[Seq[(File, String)]]] = {
    (packageBin in (project, Compile), artifact in project, managedClasspath in (project, Compile)) map {
      (jar, art, cp) => {
        def filename(a: Artifact) = a.name + a.classifier.map("-"+_).getOrElse("") + "." + a.extension
        def named(a: Attributed[File]) = (a.data, a.get(artifact.key).map(filename).getOrElse(a.data.name))
        (jar, filename(art)) +: (cp map named)
      }
    }
  }

  def createDist(base: File, libs: Seq[(File, String)], target: File, s: TaskStreams): File = {
    val lib = target / "lib"
    IO.delete(target)
    Util.copyDirectory(base, target, setExecutable = true)
    IO.createDirectory(lib)
    Util.copyMapped(libs map { case (file, name) => (file, lib / name) })
    s.log.info("Created distribution: " + target)
    target
  }

  def createTgz(dist: File, dir: File, s: TaskStreams): File = {
    val tgz = dir / (dist.name + ".tgz")
    val exitCode = Process(List("tar", "-czf", tgz.name, dist.name), dir) ! s.log
    if (exitCode != 0) sys.error("Failed to create tgz.")
    s.log.info("Created tgz: " + tgz)
    tgz
  }
}
