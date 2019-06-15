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
    bloopConfigDir) = args

  val buildRootPath = Path(buildRoot)
  val distDirPath = Path(distDir)
  val bloopConfigDirPath = Path(bloopConfigDir)

  val allStdin = scala.io.Source.stdin.mkString
  val pantsExportParsed = allStdin.parseJson.convertTo[PantsExport]

  val scalaCompilerJars = sys.env("SCALA_COMPILER_JARS_CLASSPATH")
    .split(":")
    .map(jar => buildRootPath / RelPath(jar))

  val sourceTargetTypes = Set("scala_library", "java_library", "junit_tests", "jvm_binary", "target")

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
    .toMap
  System.err.println(s"sourceTargetMap: $sourceTargetMap")

  val projects: Seq[BloopConfig.Project] = sourceTargets
    .flatMap { case (_, target) =>
      target.classesDir.map(Path(_)).map((target, _))
    }
    .map { case (target, classesDir) =>
      // TODO: ensure bloop doesn't attempt to recreate this directory if it doesn't exist
      // (e.g. after a clean-all), or pants will error out (because it expects this to be a
      // symlink!).
      val dependentJars = target.libraries.flatMap { coord =>
        pantsExportParsed.libraries.get(coord)
          .getOrElse(Seq())
          // Get libraries in all "scopes". "Scopes" here refers to a maven classifier (a parameter
          // used when resolving 3rdparty jars) -- NOT the same as `target.scope` (which is e.g. how
          // intellij classifies modules)!
          .flatMap(_._2.split(":").toSeq)
      }.map(Path(_))

      val dependentTargets = target.dependencies
        // TODO: some targets like //:scala-library won't show up -- these should be converted into
        // e.g. `addCompilerToClasspath` perhaps??
        .flatMap(sourceTargetMap.get(_))
      System.err.println(s"target: ${target.id}, deps: ${target.dependencies}, depT: $dependentTargets")

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
        options = target.zincArgs.getOrElse(Seq()).flatMap { opt =>
          if (opt.startsWith("-S")) {
            Some(opt.substring(2))
          } else { None }
        }.toList,
        jars = scalaCompilerJars.map(_.toNIO).toList,
        // TODO: when would this not be None?
        analysis = target.zincAnalysis.map(Path(_).toNIO),
        setup = Some(BloopConfig.CompileSetup(
          // TODO: Determine whether the CompileOrder refers to a global "scala first, then java"
          // (e.g. maven only allows one), or within a specific target (likely the first)!
          order = BloopConfig.Mixed,
          addLibraryToBootClasspath = true,
          addCompilerToClasspath = true,
          addExtraJarsToClasspath = true,
          manageBootClasspath = true,
          filterLibraryFromClasspath = false
        ))
      )

      val javaConfig = BloopConfig.Java(options = target.zincArgs.getOrElse(Seq()).flatMap { opt =>
        if (opt.startsWith("-C")) {
          Some(opt.substring(2))
        } else { None }
      }.toList)

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
