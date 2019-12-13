/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.compiler

import java.io.{File}
import java.util.function.{ Function => JFunction }

import scala.compat.java8.OptionConverters._

import sbt.internal.inc.ReporterManager
import sbt.internal.inc.ZincUtil
import sbt.io.IO
import sbt.util.Logger
import xsbti.{Position, Problem, Severity, ReporterConfig, ReporterUtil}
import xsbti.compile.{
  AnalysisStore,
  ClasspathOptionsUtil,
  CompileOptions,
  CompileOrder,
  Compilers,
  Inputs,
  PreviousResult,
  Setup
}
import org.pantsbuild.zinc.analysis.AnalysisMap
import org.pantsbuild.zinc.scalautil.ScalaUtils
import org.pantsbuild.zinc.compiler.CompilerUtils.newScalaCompiler

object InputUtils {
  /**
   * Create Inputs based on command-line settings.
   */
  def create(
    settings: Settings,
    analysisMap: AnalysisMap,
    previousResult: PreviousResult,
    log: Logger
  ): Inputs = {
    import settings._

    val scalaJars = Defaults.scalaJars
    log.debug(s"Selected scala jars: $scalaJars")

    val instance = ScalaUtils.scalaInstance(scalaJars.compiler, scalaJars.extra, scalaJars.library)
    val compiledBridgeJar = Defaults.compiledBridgeJar.get
    log.debug(s"Selected CompiledBridgeJar $compiledBridgeJar")
    val compilers = ZincUtil.compilers(instance, ClasspathOptionsUtil.auto, settings.javaHome, newScalaCompiler(instance, compiledBridgeJar))

    // TODO: Remove duplication once on Scala 2.12.x.
    val positionMapper =
      new JFunction[Position, Position] {
        override def apply(p: Position): Position = p
      }

    val compileOptions =
      CompileOptions
        .create()
        .withClasspath(
          autoClasspath(
            classesDirectory,
            compilers.scalac().scalaInstance().allJars,
            javaOnly,
            classpath
          ).toArray
        )
        .withSources(sources.toArray)
        .withClassesDirectory(classesDirectory)
        .withScalacOptions(scalacOptions.toArray)
        .withJavacOptions(javacOptions.toArray)
        .withOrder(compileOrder)

    val reporter =
      if (settings.consoleLog.useBarebonesLogger) {
        ReporterUtil.getReporter(
          BareBonesLogger(settings.consoleLog.logLevel), ReporterManager.getDefaultReporterConfig)
      } else {
        ReporterUtil.getDefault(
        ReporterUtil.getDefaultReporterConfig()
          .withMaximumErrors(Int.MaxValue)
          .withUseColor(settings.consoleLog.color)
          .withMsgFilters(settings.consoleLog.msgPredicates.toArray)
          .withFileFilters(settings.consoleLog.filePredicates.toArray)
          .withLogLevel(settings.consoleLog.javaLogLevel)
          .withPositionMapper(positionMapper)
        )
      }
    val setup =
      Setup.create(
        analysisMap.getPCELookup,
        false,
        settings.analysis.cache,
        CompilerUtils.getGlobalsCache,
        incOptions.options(log),
        reporter,
        None.asJava,
        Array()
      )

    Inputs.create(
      compilers,
      compileOptions,
      setup,
      previousResult
    )
  }

  /**
   * Load the analysis for the destination, creating it if necessary.
   */
  def loadDestinationAnalysis(
    settings: Settings,
    analysisMap: AnalysisMap,
    log: Logger
  ): (AnalysisStore, PreviousResult) = {
    def load() = {
      val analysisStore = analysisMap.cachedStore(settings.analysis.cache)
      analysisStore.get().asScala match {
        case Some(a) => (analysisStore, Some(a.getAnalysis), Some(a.getMiniSetup))
        case _ => (analysisStore, None, None)
      }
    }

    // Try loading, and optionally remove/retry on failure.
    val (analysisStore, previousAnalysis, previousSetup) =
      try {
        load()
      } catch {
        case e: Throwable if settings.analysis.clearInvalid =>
          // Remove the corrupted analysis and output directory.
          log.warn(s"Failed to load analysis from ${settings.analysis.cache} ($e): will execute a clean compile.")
          IO.delete(settings.analysis.cache)
          IO.delete(settings.classesDirectory)
          load()
      }
    (analysisStore, PreviousResult.create(previousAnalysis.asJava, previousSetup.asJava))
  }

  /**
   * Automatically add the output directory and scala library to the classpath.
   */
  def autoClasspath(classesDirectory: File, allScalaJars: Seq[File], javaOnly: Boolean, classpath: Seq[File]): Seq[File] = {
    if (javaOnly) classesDirectory +: classpath
    else splitScala(allScalaJars) match {
      case Some(scalaJars) => classesDirectory +: scalaJars.library +: classpath
      case None            => classesDirectory +: classpath
    }
  }

  /**
   * Distinguish the compiler and library jars.
   */
  def splitScala(jars: Seq[File], excluded: Set[String] = Set.empty): Option[ScalaJars] = {
    var  filtered = jars filterNot (excluded contains _.getName)
    // Added because the jars can be the entire classpath if using the default value.
    filtered = filtered filter (_.getName matches ".*scala.*")
    val (compiler, other) = filtered partition (_.getName matches ScalaCompiler.pattern)
    val ScalaCompiler.regex(library_version) = compiler(0).getName
    val VersionedScalaLibraryJar = JarFile("scala-library", version=Some(library_version))
    val (library, extra) = other partition (_.getName matches VersionedScalaLibraryJar.pattern)
    if (compiler.nonEmpty && library.nonEmpty) Some(ScalaJars(compiler(0), library(0), extra)) else None
  }

  //
  // Default setup
  //

  val ScalaCompiler            = JarFile("scala-compiler")
  val ScalaLibrary             = JarFile("scala-library")
  val ScalaReflect             = JarFile("scala-reflect")
  val ScalaCompilerBridge      = JarFile("scala-compiler-bridge")

  // Scala jars default to jars matching the JarFile patterns on the jvm classpath.
  object Defaults {

    val classpath = IO.parseClasspath(System.getProperty("java.class.path"))
    val (maybeCompiledBridgeJar, other) = classpath partition (_.getName matches ScalaCompilerBridge.pattern)
    val compiledBridgeJar = if (maybeCompiledBridgeJar.nonEmpty) Some(maybeCompiledBridgeJar(0)) else None
    // try to locate scala jars from the current classpath.
    val classpathScalaJars   = splitScala(other)
    val scalaCompiler        = ScalaCompiler.default
    val scalaLibrary         = ScalaLibrary.default
    val scalaExtra           = Seq(ScalaReflect.default)
    val scalaJars            = classpathScalaJars getOrElse ScalaJars(scalaCompiler, scalaLibrary, scalaExtra)
    val scalaExcluded = Set("jansi.jar", "jline.jar", "scala-partest.jar", "scala-swing.jar", "scalacheck.jar", "scalap.jar")
  }

  /**
   * Jar file description for locating jars.
   */
  case class JarFile(name: String, version: Option[String] = None, classifier: Option[String] = None) {
    val versionPattern = s"-?(${version getOrElse ".*"})?"
    val classifierString = classifier map ("-" + _) getOrElse ""
    val extension = "jar"
    val pattern = name + versionPattern + classifierString + "\\." + extension
    val regex = pattern.r
    val default = new File(name + classifierString + "." + extension)
  }

  object JarFile {
    def apply(name: String, classifier: String): JarFile = JarFile(name, Some(classifier))
  }

  /**
   * The scala jars split into compiler, library, and extra.
   */
  case class ScalaJars(compiler: File, library: File, extra: Seq[File])
}
