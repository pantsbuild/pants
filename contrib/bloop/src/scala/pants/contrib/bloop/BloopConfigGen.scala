package pants.contrib.bloop

import pants.contrib.bloop.PantsExportProtocol._

import ammonite.ops._
import bloop.config.{Config => BloopConfig, write => BloopConfigWrite}
import spray.json._

import scala.sys

object BloopConfigGen extends App {
  val Array(
    buildRoot,
    scalaVersion,
    distDir,
    zincCompileDir,
    bloopConfigDir) = args

  val buildRootPath = Path(buildRoot)
  val distDirPath = Path(distDir)
  val zincBasePath = Path(zincCompileDir)
  val bloopConfigDirPath = Path(bloopConfigDir)

  val allStdin = scala.io.Source.stdin.mkString
  val pantsExportParsed = allStdin.parseJson.convertTo[PantsExport]

  val scalacEnvArgs = sys.env("SCALAC_ARGS").parseJson.convertTo[Seq[String]]
  val javacEnvArgs = sys.env("JAVAC_ARGS").parseJson.convertTo[Seq[String]]

  val scalaCompilerJars = sys.env("SCALA_COMPILER_JARS_CLASSPATH")
    .split(":")
    .map(jar => buildRootPath / RelPath(jar))

  val sourceTargetTypes = Set("scala_library", "java_library", "junit_tests", "jvm_binary")

  val sourceTargets = pantsExportParsed.targets.filter { case (_, target) =>
    sourceTargetTypes(target.targetType)
  }
  // Refer to dependencies by their `id`, not by `depName` (which is a pants target spec -- not
  // allowed).
  val sourceTargetMap = sourceTargets
    // TODO: we drop target.scope here when calling .distinct -- is this flattening our graph too
    // much? Should intellij/BSP have this info? Because pants resolves 3rdparty artifacts itself,
    // we may need to figure out the right way to pipe this into bloop.
    .map { case (depName, target) => (depName, target.id) }
    .toSeq
    .distinct
    .toMap

  val projects: Seq[BloopConfig.Project] = sourceTargets
    .map { case (_, target) =>
      // TODO: ensure bloop doesn't attempt to recreate this directory if it doesn't exist
      // (e.g. after a clean-all), or pants will error out (because it expects this to be a
      // symlink!).
      val classesDir = zincBasePath / "current" / RelPath(target.id) / "current" / "classes"
      val dependentJars = target.libraries.flatMap { coord =>
        pantsExportParsed.libraries.get(coord)
          .getOrElse(Seq())
          // Get libraries in all "scopes". "Scopes" here refers to a maven classifier (a parameter
          // used when resolving 3rdparty jars) -- NOT the same as `target.scope` (which is e.g. how
          // intellij classifies modules)!
          .flatMap(_._2.split(":").toSeq)
      }.map(Path(_))

      val dependentTargets = target.dependencies
        .map(_.flatMap(sourceTargetMap.get(_)))
        .getOrElse(Seq())

      val sources = target.sources.getOrElse(Seq())
        .map(srcRelPath => buildRootPath / RelPath(srcRelPath))

      val curPlatformString = target.platform
        .getOrElse(pantsExportParsed.jvmPlatforms.defaultPlatform)
      // NB: We can assume pants has ensured all targets specifying a jvm platform map to an
      // existing (i.e. defined in the pants jvm platforms) platform!
      val curPlatform = pantsExportParsed.jvmPlatforms.platforms(curPlatformString)
      // TODO: do the `strict` vs non-`strict` values mean anything here?
      val javaHome = Path(pantsExportParsed.preferredJvmDistributions(curPlatformString).nonStrict)
      val jvmConfig = BloopConfig.JvmConfig(
        home = Some(javaHome.toNIO),
        options = curPlatform.args.toList,
      )
      val bloopPlatform = BloopConfig.Platform.Jvm(
        config = jvmConfig,
        mainClass = target.main,
      )

      val scalaConfig = BloopConfig.Scala(
        // TODO: pants resolves this compiler itself (and the user can override it!!) -- we would
        // like to have bloop ignore these!!/
        organization = "org.scala-lang",
        name = "scala-compiler",
        version = scalaVersion,
        options = scalacEnvArgs.toList,
        jars = scalaCompilerJars.map(_.toNIO).toList,
        // TODO: when would this not be None?
        analysis = None,
        setup = Some(BloopConfig.CompileSetup(
          // TODO: Determine whether the CompileOrder refers to a global "scala first, then java"
          // (e.g. maven only allows one), or within a specific target (likely the first)!
          order = BloopConfig.Mixed,
          addLibraryToBootClasspath = false,
          addCompilerToClasspath = false,
          addExtraJarsToClasspath = false,
          manageBootClasspath = false,
          filterLibraryFromClasspath = false
        ))
      )

      val javaConfig = BloopConfig.Java(options = javacEnvArgs.toList)

      BloopConfig.Project(
        name = target.id,
        directory = (buildRootPath / RelPath(target.specPath)).toNIO,
        sources = sources.map(_.toNIO).toList,
        dependencies = dependentTargets.toList,
        classpath = dependentJars.map(_.toNIO).toList,
        out = distDirPath.toNIO,
        classesDir = classesDir.toNIO,
        // TODO: parse resources targets from the export json!
        resources = None,
        `scala` = Some(scalaConfig),
        java = Some(javaConfig),
        sbt = None,
        // TODO: add test configs for junit_tests() targets!!
        test = None,
        platform = Some(bloopPlatform),
        // NB: Pants does the resolution itself!!
        resolution = None
      )
    }
    .toSeq

  projects.foreach { proj =>
    val bloopConfigFile = BloopConfig.File(BloopConfig.File.LatestVersion, proj)
    val outputFile = bloopConfigDirPath / RelPath(s"${proj.name}.json")
    BloopConfigWrite(bloopConfigFile, outputFile.toNIO)
  }

  println(s"bbbbb!!!:\n${pantsExportParsed.toJson.prettyPrint}")
}
