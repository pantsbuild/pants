/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.zinc

import java.io.File
import java.util.{ List => JList }
import sbt.Path._
import scala.collection.JavaConverters._

/**
 * All setup options for an zinc compiler.
 */
case class Setup(
  scalaCompiler: File,
  scalaLibrary: File,
  scalaExtra: Seq[File],
  sbtInterface: File,
  compilerInterfaceSrc: File,
  javaHome: Option[File],
  cacheDir: File)

object Setup {
  val Command = "zinc"
  val Description = "scala incremental compiler"

  val HomeProperty = prop("home")
  val DirProperty = prop("dir")

  val ScalaCompilerId = "scala-compiler"
  val ScalaLibraryId = "scala-library"

  val ScalaCompilerName = "scala-compiler.jar"
  val ScalaLibraryName = "scala-library.jar"
  val SbtInterfaceName = "sbt-interface.jar"
  val CompilerInterfaceSourcesName = "compiler-interface-sources.jar"

  /**
   * Create compiler setup from command-line settings.
   */
  def apply(settings: Settings): Setup = {
    import settings._
    val (compiler, library, extra) = scalaJars(scala)
    setup(compiler, library, extra, Defaults.sbtInterface, Defaults.compilerInterfaceSrc, javaHome)
  }

  /**
   * Create normalised and defaulted Setup.
   */
  def setup(
    scalaCompiler: File,
    scalaLibrary: File,
    scalaExtra: Seq[File],
    sbtInterface: File,
    compilerInterfaceSrc: File,
    javaHomeDir: Option[File]): Setup =
  {
    val normalise: File => File = { _.getCanonicalFile }
    val compilerJar = normalise(scalaCompiler)
    val libraryJar = normalise(scalaLibrary)
    val extraJars = scalaExtra map normalise
    val javaHome = javaHomeDir map normalise
    val cacheDir = zincCacheDir
    Setup(compilerJar, libraryJar, extraJars, sbtInterface, compilerInterfaceSrc, javaHome, cacheDir)
  }

  /**
   * Java API for creating Setup.
   */
  def create(
    scalaCompiler: File,
    scalaLibrary: File,
    scalaExtra: JList[File],
    sbtInterface: File,
    compilerInterfaceSrc: File,
    javaHome: File): Setup =
  setup(
    scalaCompiler,
    scalaLibrary,
    scalaExtra.asScala,
    sbtInterface,
    compilerInterfaceSrc,
    Option(javaHome)
  )

  /**
   * Select the scala jars.
   *
   * Prefer the explicit scala-compiler, scala-library, and scala-extra settings,
   * then the scala-path setting, then the scala-home setting. Default to bundled scala.
   */
  def scalaJars(scala: ScalaLocation): (File, File, Seq[File]) = {
    val (compiler, library, extra) = {
      splitScala(scala.path) orElse
      splitScala(allLibs(scala.home), Defaults.scalaExcluded) getOrElse
      Defaults.scalaJars
    }
    (scala.compiler getOrElse compiler, scala.library getOrElse library, scala.extra ++ extra)
  }

  /**
   * Distinguish the compiler and library jars.
   */
  def splitScala(jars: Seq[File], excluded: Set[String] = Set.empty): Option[(File, File, Seq[File])] = {
    val filtered = jars filterNot (excluded contains _.getName)
    val (compiler, other) = filtered partition (_.getName contains ScalaCompilerId)
    val (library, extra) = other partition (_.getName contains ScalaLibraryId)
    if (compiler.nonEmpty && library.nonEmpty) Some(compiler(0), library(0), extra) else None
  }

  /**
   * Zinc cache directory.
   */
  def zincCacheDir = Defaults.zincDir / zincVersion.published

  //
  // Default setup
  //

  object Defaults {
    val userHome = Util.fileProperty("user.home")
    val zincDir = Util.optFileProperty(DirProperty).getOrElse(userHome / ("." + Command)).getCanonicalFile
    val zincHome = Util.optFileProperty(HomeProperty).map(_.getCanonicalFile)

    val sbtInterface = optLibOrEmpty(zincHome, SbtInterfaceName)
    val compilerInterfaceSrc = optLibOrEmpty(zincHome, CompilerInterfaceSourcesName)

    val scalaCompiler = optLibOrEmpty(zincHome, ScalaCompilerName)
    val scalaLibrary = optLibOrEmpty(zincHome, ScalaLibraryName)
    val scalaExtra = Seq.empty[File]
    val scalaJars = (scalaCompiler, scalaLibrary, scalaExtra)
    val defaultScalaExcluded = Set("jansi.jar", "jline.jar", "scala-partest.jar", "scala-swing.jar", "scalacheck.jar", "scalap.jar")
    val scalaExcluded = Util.stringSetProperty(prop("scala.excluded"), defaultScalaExcluded)

    val cacheLimit = Util.intProperty(prop("cache.limit"), 5)
    val compilerCacheLimit = Util.intProperty(prop("compiler.cache.limit"), cacheLimit)
    val residentCacheLimit = Util.intProperty(prop("resident.cache.limit"), cacheLimit)
    val analysisCacheLimit = Util.intProperty(prop("analysis.cache.limit"), cacheLimit)
    val loggerCacheLimit = Util.intProperty(prop("logger.cache.limit"), cacheLimit)
  }

  def prop(name: String) = Command + "." + name

  def allLibs(homeDir: Option[File]): Seq[File] = {
    homeDir map { home => (home / "lib" ** "*.jar").get } getOrElse Seq.empty
  }

  def optLib(homeDir: Option[File], name: String): Option[File] = {
    allLibs(homeDir) find (_.getName == name)
  }

  def optLibOrEmpty(homeDir: Option[File], name: String): File = {
    optLib(homeDir, name) getOrElse new File("")
  }

  //
  // Zinc version
  //

  /**
   * Full zinc version info.
   */
  case class Version(published: String, timestamp: String, commit: String)

  /**
   * Get the zinc version from a generated properties file.
   */
  lazy val zincVersion: Version = {
    val props = Util.propertiesFromResource("zinc.version.properties", getClass.getClassLoader)
    Version(
      props.getProperty("version", "unknown"),
      props.getProperty("timestamp", ""),
      props.getProperty("commit", "")
    )
  }

  /**
   * For snapshots the zinc version includes timestamp and commit.
   */
  lazy val versionString: String = {
    import zincVersion._
    if (published.endsWith("-SNAPSHOT")) "%s %s-%s" format (published, timestamp, commit take 10)
    else published
  }

  /**
   * Print the zinc version to standard out.
   */
  def printVersion(): Unit = println("%s (%s) %s" format (Command, Description, versionString))

  //
  // Debug
  //

  /**
   * Debug output for inputs.
   */
  def debug(setup: Setup, log: xsbti.Logger): Unit = {
    show(setup, s => log.debug(sbt.Logger.f0(s)))
  }

  /**
   * Debug output for compiler setup.
   */
  def show(setup: Setup, output: String => Unit): Unit = {
    import setup._
    val values = Seq(
      "scala compiler" -> scalaCompiler,
      "scala library" -> scalaLibrary,
      "scala extra" -> scalaExtra,
      "sbt interface" -> sbtInterface,
      "compiler interface sources" -> compilerInterfaceSrc,
      "java home" -> javaHome,
      "cache directory" -> cacheDir)
    Util.show(("Setup", values), output)
  }
}
