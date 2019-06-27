package pants.contrib.bloop.config

import pants.contrib.bloop.config.PantsExportProtocol._

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

  // TODO: unused for now! It's probably preferable to do the target filtering on the pants side.
  // val sourceTargetTypes = sys.env("PANTS_TARGET_TYPES")
  //   .split(":")
  //   .toSet
  // val sourceTargets = pantsExportParsed.targets.filter { case (_, target) =>
  //   sourceTargetTypes(target.targetType)
  // }
  val sourceTargets = pantsExportParsed.targets

  // Refer to dependencies by their `id`, not by `depName` (which is a pants target spec -- not
  // allowed).
  val sourceTargetMap = sourceTargets.toMap
  val sourceTargetIdMap = sourceTargets
    // TODO: we drop target.scope here when calling .distinct -- is this flattening our graph too
    // much? Should intellij/BSP have this info? Because pants resolves 3rdparty artifacts itself,
    // we may need to figure out the right way to pipe this into bloop.
    .map { case (depName, target) => (depName, target.id) }
    .toMap
  System.err.println(s"sourceTargetIdMap: $sourceTargetIdMap")

  val projects: Seq[BloopConfig.Project] = sourceTargets
    .flatMap { case (_, target) =>
      target.classesDir.map(Path(_)).map((target, _))
    }
    .map { case (target, classesDir) =>
      val dependentTargetIds = target.dependencies
        // TODO: some targets like //:scala-library won't show up -- these should be converted into
        // e.g. `addCompilerToClasspath` perhaps??
        .flatMap(sourceTargetIdMap.get(_))
      System.err.println(s"target: ${target.id}, deps: ${target.dependencies}, depT: $dependentTargetIds")

      val dependencyClasspath = target.dependencyClasspath.getOrElse(Seq()).map(Path(_))

      val sourceTargetClassDirs = target.dependencies
        .flatMap(sourceTargetMap.get(_))
        .flatMap(_.classesDir.map(Path(_)))

      // TODO: Metals currently doesn't handle complete source file paths
      // (https://github.com/scalameta/metals/issues/770), although bloop/BSP does and may require
      // it to compile correctly. Until that is fixed, we can use "source roots" like we do for the
      // IntelliJ plugin to get the IDE experience working.
      // val sources = target.sources.getOrElse(Seq())
      //   .map(srcRelPath => buildRootPath / RelPath(srcRelPath))
      val sources = target.sourceRoots.map(_.sourceRootPath).map(Path(_))

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
        dependencies = dependentTargetIds.toList,
        classpath = (sourceTargetClassDirs ++ dependencyClasspath).map(_.toNIO).toList,
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
}
