/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import java.util.{ List => JList }
import sbt.Path._
import scala.collection.JavaConverters._

/**
 * All setup options for a zinc compiler.
 */
case class Setup(
  scalaCompiler: File,
  scalaLibrary: File,
  scalaExtra: Seq[File],
  sbtInterface: File,
  compilerInterfaceSrc: File,
  javaHome: Option[File],
  forkJava: Boolean,
  cacheDir: File,
  logOptions: LogOptions)

/**
 * Jar file description for locating jars.
 */
case class JarFile(name: String, classifier: Option[String] = None) {
  val versionPattern = "(-.*)?"
  val classifierString = classifier map ("-" + _) getOrElse ""
  val extension = "jar"
  val pattern = name + versionPattern + classifierString + "." + extension
  val default = name + classifierString + "." + extension
}

object JarFile {
  def apply(name: String, classifier: String): JarFile = JarFile(name, Some(classifier))
}

/**
 * The scala jars split into compiler, library, and extra.
 */
case class ScalaJars(compiler: File, library: File, extra: Seq[File])

object Setup {
  val Command     = "zinc"
  val Description = "scala incremental compiler"

  val HomeProperty = prop("home")
  val DirProperty  = prop("dir")

  val ScalaCompiler            = JarFile("scala-compiler")
  val ScalaLibrary             = JarFile("scala-library")
  val ScalaReflect             = JarFile("scala-reflect")
  val SbtInterface             = JarFile("sbt-interface")
  val CompilerInterfaceSources = JarFile("compiler-interface", "sources")

  /**
   * Create compiler setup from command-line settings.
   */
  def apply(settings: Settings): Setup = {
    val scalaJars = selectScalaJars(settings.scala)
    val (sbtInterface, compilerInterfaceSrc) = selectSbtJars(settings.sbt)
    setup(scalaJars.compiler, scalaJars.library, scalaJars.extra, sbtInterface, compilerInterfaceSrc, settings.javaHome, settings.forkJava, settings.logOptions)
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
    javaHomeDir: Option[File],
    forkJava: Boolean,
    logOptions: LogOptions): Setup =
  {
    val normalise: File => File = { _.getAbsoluteFile }
    val compilerJar          = normalise(scalaCompiler)
    val libraryJar           = normalise(scalaLibrary)
    val extraJars            = scalaExtra map normalise
    val sbtInterfaceJar      = normalise(sbtInterface)
    val compilerInterfaceJar = normalise(compilerInterfaceSrc)
    val javaHome             = javaHomeDir map normalise
    val cacheDir             = zincCacheDir
    Setup(compilerJar, libraryJar, extraJars, sbtInterfaceJar, compilerInterfaceJar, javaHome, forkJava, cacheDir, logOptions)
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
    javaHome: File,
    forkJava: Boolean,
    logOptions: LogOptions): Setup =
  setup(
    scalaCompiler,
    scalaLibrary,
    scalaExtra.asScala,
    sbtInterface,
    compilerInterfaceSrc,
    Option(javaHome),
    forkJava,
    logOptions
  )

  @deprecated("Use variant that takes forkJava parameter instead.", "0.3.6")
  def create(
    scalaCompiler: File,
    scalaLibrary: File,
    scalaExtra: JList[File],
    sbtInterface: File,
    compilerInterfaceSrc: File,
    javaHome: File): Setup =
      create(scalaCompiler, scalaLibrary, scalaExtra, sbtInterface,
        compilerInterfaceSrc, javaHome, false, LogOptions())

  /**
   * Java API for creating Setup with ScalaLocation and SbtJars.
   */
  def create(
    scalaLocation: ScalaLocation,
    sbtJars: SbtJars,
    javaHome: File,
    forkJava: Boolean): Setup =
  {
    val scalaJars = selectScalaJars(scalaLocation)
    val (sbtInterface, compilerInterfaceSrc) = selectSbtJars(sbtJars)
    setup(
      scalaJars.compiler,
      scalaJars.library,
      scalaJars.extra,
      sbtInterface,
      compilerInterfaceSrc,
      Option(javaHome),
      forkJava,
      LogOptions()
    )
  }

  @deprecated("Use variant that takes forkJava parameter instead.", "0.3.6")
  def create(
    scalaLocation: ScalaLocation,
    sbtJars: SbtJars,
    javaHome: File): Setup = create(scalaLocation, sbtJars, javaHome, false)

  /**
   * Select the scala jars.
   *
   * Prefer the explicit scala-compiler, scala-library, and scala-extra settings,
   * then the scala-path setting, then the scala-home setting. Default to bundled scala.
   */
  def selectScalaJars(scala: ScalaLocation): ScalaJars = {
    val jars = {
      splitScala(scala.path) orElse
      splitScala(allLibs(scala.home), Defaults.scalaExcluded) getOrElse
      Defaults.scalaJars
    }
    ScalaJars(
      scala.compiler getOrElse jars.compiler,
      scala.library getOrElse jars.library,
      scala.extra ++ jars.extra
    )
  }

  /**
   * Distinguish the compiler and library jars.
   */
  def splitScala(jars: Seq[File], excluded: Set[String] = Set.empty): Option[ScalaJars] = {
    val filtered = jars filterNot (excluded contains _.getName)
    val (compiler, other) = filtered partition (_.getName matches ScalaCompiler.pattern)
    val (library, extra) = other partition (_.getName matches ScalaLibrary.pattern)
    if (compiler.nonEmpty && library.nonEmpty) Some(ScalaJars(compiler(0), library(0), extra)) else None
  }

  /**
   * Select the sbt jars.
   */
  def selectSbtJars(sbt: SbtJars): (File, File) = {
    val sbtInterface = sbt.sbtInterface getOrElse Defaults.sbtInterface
    val compilerInterfaceSrc = sbt.compilerInterfaceSrc getOrElse Defaults.compilerInterfaceSrc
    (sbtInterface, compilerInterfaceSrc)
  }

  /**
   * Zinc cache directory.
   */
  def zincCacheDir = Defaults.zincDir / zincVersion.published

  /**
   * Verify that necessary jars exist.
   */
  def verify(setup: Setup, log: LoggerRaw): Boolean = {
    requireFile(setup.scalaCompiler, log) &&
    requireFile(setup.scalaLibrary, log) &&
    requireFile(setup.sbtInterface, log) &&
    requireFile(setup.compilerInterfaceSrc, log)
  }

  /**
   * Check file exists. Log error if it doesn't.
   */
  def requireFile(file: File, log: LoggerRaw): Boolean = {
    val exists = file.exists
    if (!exists) log.error("Required file not found: " + file.getName)
    exists
  }

  //
  // Default setup
  //

  object Defaults {
    val userHome = Util.fileProperty("user.home")
    val userDir  = Util.fileProperty("user.dir")
    val zincDir  = Util.optFileProperty(DirProperty).getOrElse(userHome / ("." + Command)).getCanonicalFile
    val zincHome = Util.optFileProperty(HomeProperty).map(_.getCanonicalFile)

    val sbtInterface         = optLibOrDefault(zincHome, SbtInterface)
    val compilerInterfaceSrc = optLibOrDefault(zincHome, CompilerInterfaceSources)

    val scalaCompiler        = optLibOrDefault(zincHome, ScalaCompiler)
    val scalaLibrary         = optLibOrDefault(zincHome, ScalaLibrary)
    val scalaExtra           = Seq(optLibOrDefault(zincHome, ScalaReflect))
    val scalaJars            = ScalaJars(scalaCompiler, scalaLibrary, scalaExtra)
    val defaultScalaExcluded = Set("jansi.jar", "jline.jar", "scala-partest.jar", "scala-swing.jar", "scalacheck.jar", "scalap.jar")
    val scalaExcluded        = Util.stringSetProperty(prop("scala.excluded"), defaultScalaExcluded)

    val cacheLimit         = Util.intProperty(prop("cache.limit"), 5)
    val analysisCacheLimit = Util.intProperty(prop("analysis.cache.limit"), cacheLimit)
    val compilerCacheLimit = Util.intProperty(prop("compiler.cache.limit"), cacheLimit)
    val residentCacheLimit = Util.intProperty(prop("resident.cache.limit"), 0)
  }

  def prop(name: String) = Command + "." + name

  def allLibs(homeDir: Option[File]): Seq[File] = {
    homeDir map { home => (home / "lib" ** "*.jar").get } getOrElse Seq.empty
  }

  def optLib(homeDir: Option[File], jar: JarFile): Option[File] = {
    allLibs(homeDir) find (_.getName matches jar.pattern)
  }

  def optLibOrDefault(homeDir: Option[File], jar: JarFile): File = {
    optLib(homeDir, jar) getOrElse new File(jar.default)
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
      "scala compiler"             -> scalaCompiler,
      "scala library"              -> scalaLibrary,
      "scala extra"                -> scalaExtra,
      "sbt interface"              -> sbtInterface,
      "compiler interface sources" -> compilerInterfaceSrc,
      "java home"                  -> javaHome,
      "fork java"                  -> forkJava,
      "cache directory"            -> cacheDir)
    Util.show(("Setup", values), output)
  }
}
