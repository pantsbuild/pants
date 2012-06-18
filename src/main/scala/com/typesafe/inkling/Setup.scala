/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import java.io.File
import sbt.Path._

/**
 * All setup options for an inkling compiler.
 */
case class Setup(
  scalaCompiler: File,
  scalaLibrary: File,
  scalaExtra: Seq[File],
  sbtInterface: File,
  compilerInterfaceSrc: File,
  javaHome: Option[File],
  cacheDir: File,
  maxCompilers: Int,
  logging: String)

object Setup {
  val Command = "inkling"
  val Description = "scala incremental compiler"

  val HomeProperty = prop("home")
  val DirProperty = prop("dir")

  val ScalaCompilerName = "scala-compiler.jar"
  val ScalaLibraryName = "scala-library.jar"

  val SbtInterfaceName = "sbt-interface.jar"
  val CompilerInterfaceSourcesName = "compiler-interface-sources.jar"

  /**
   * Create compiler setup from command-line settings.
   */
  def apply(settings: Settings): Setup = {
    val (compiler, library, extra) = scalaJars(settings.scalaPath, settings.scalaHome)
    val compilerJar = compiler.getCanonicalFile
    val libraryJar = library.getCanonicalFile
    val extraJars = extra map (_.getCanonicalFile)
    val javaHome = settings.javaHome map (_.getCanonicalFile)
    val cacheDir = Defaults.inklingDir / inklingVersion.published
    val maxCompilers = settings.residentLimit
    val logging = Util.logging(settings.quiet, settings.logLevel)
    Setup(compilerJar, libraryJar, extraJars, Defaults.sbtInterface, Defaults.compilerInterfaceSrc, javaHome, cacheDir, maxCompilers, logging)
  }

  /**
   * Select the scala jars.
   * Prefer the scala-path setting, then the scala-home setting, otherwise use bundled scala.
   */
  def scalaJars(scalaPath: Seq[File], scalaHome: Option[File]): (File, File, Seq[File]) = {
    splitScala(scalaPath) orElse splitScala(allLibs(scalaHome), Defaults.scalaExcluded) getOrElse Defaults.scalaJars
  }

  /**
   * Distinguish the compiler and library jars.
   */
  def splitScala(jars: Seq[File], excluded: Set[String] = Set.empty): Option[(File, File, Seq[File])] = {
    val filtered = jars filterNot (excluded contains _.getName)
    val (compiler, other) = filtered partition (_.getName == ScalaCompilerName)
    val (library, extra) = other partition (_.getName == ScalaLibraryName)
    if (compiler.nonEmpty && library.nonEmpty) Some(compiler(0), library(0), extra) else None
  }

  //
  // Default setup
  //

  object Defaults {
    val userHome = Util.fileProperty("user.home")
    val inklingDir = Util.optFileProperty(DirProperty).getOrElse(userHome / ("." + Command)).getCanonicalFile
    val inklingHome = Util.optFileProperty(HomeProperty).map(_.getCanonicalFile)

    val sbtInterface = optLibOrEmpty(inklingHome, SbtInterfaceName)
    val compilerInterfaceSrc = optLibOrEmpty(inklingHome, CompilerInterfaceSourcesName)

    val scalaCompiler = optLibOrEmpty(inklingHome, ScalaCompilerName)
    val scalaLibrary = optLibOrEmpty(inklingHome, ScalaLibraryName)
    val scalaExtra = Seq.empty[File]
    val scalaJars = (scalaCompiler, scalaLibrary, scalaExtra)
    val defaultScalaExcluded = Set("jansi.jar", "jline.jar", "scala-partest.jar", "scala-swing.jar", "scalacheck.jar", "scalap.jar")
    val scalaExcluded = Util.stringSetProperty(prop("scala.excluded"), defaultScalaExcluded)

    val cacheLimit = Util.intProperty(prop("cache.limit"), 5)
    val loggerCacheLimit = Util.intProperty(prop("logger.cache.limit"), cacheLimit)
    val compilerCacheLimit = Util.intProperty(prop("compiler.cache.limit"), cacheLimit)
    val analysisCacheLimit = Util.intProperty(prop("analysis.cache.limit"), cacheLimit)
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
  // Inkling version
  //

  /**
   * Full inkling version info.
   */
  case class Version(published: String, timestamp: String, commit: String)

  /**
   * Get the inkling version from a generated properties file.
   */
  lazy val inklingVersion: Version = {
    val props = Util.propertiesFromResource("inkling.version.properties", getClass.getClassLoader)
    Version(
      props.getProperty("version", "unknown"),
      props.getProperty("timestamp", ""),
      props.getProperty("commit", "")
    )
  }

  /**
   * For snapshots the inkling version includes timestamp and commit.
   */
  lazy val versionString: String = {
    import inklingVersion._
    if (published.endsWith("-SNAPSHOT")) "%s %s-%s" format (published, timestamp, commit take 10)
    else published
  }

  /**
   * Print the inkling version to standard out.
   */
  def printVersion(): Unit = println("%s (%s) %s" format (Command, Description, versionString))

  //
  // Debug
  //

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
      "cache directory" -> cacheDir,
      "resident compiler limit" -> maxCompilers,
      "logging" -> logging)
    Util.show(("setup", values), output)
  }
}
