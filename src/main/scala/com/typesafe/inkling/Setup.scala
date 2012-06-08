/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import java.io.File
import sbt.Path._

case class Setup(
  scalaCompiler: File,
  scalaLibrary: File,
  sbtInterface: File,
  compilerInterfaceSrc: File,
  javaHome: Option[File],
  cacheDir: File,
  maxCompilers: Int,
  logging: String)

object Setup {
  val Command = "inkling"
  val Description = "scala incremental compiler"

  def apply(settings: Settings): Setup = {
    import settings._
    val compiler = chooseScalaCompiler(scalaCompiler, scalaHome)
    val library = chooseScalaLibrary(scalaLibrary, scalaHome)
    val cacheDir = Defaults.inklingDir / inklingVersion.published
    val logging = Util.logging(settings.quiet, settings.logLevel)
    Setup(compiler, library, Defaults.sbtInterface, Defaults.compilerInterfaceSrc, javaHome, cacheDir, residentLimit, logging)
  }

  def chooseScalaCompiler(userSet: Option[File], scalaHome: Option[File]) = {
    userSet orElse optLib(scalaHome, "scala-compiler.jar") getOrElse Defaults.scalaCompiler
  }

  def chooseScalaLibrary(userSet: Option[File], scalaHome: Option[File]) = {
    userSet orElse optLib(scalaHome, "scala-library.jar") getOrElse Defaults.scalaLibrary
  }

  object Defaults {
    val homeProperty = prop("home")

    val userHome = Util.fileProperty("user.home")
    val inklingDir = Util.optFileProperty(prop("dir")).getOrElse(userHome / ("." + Command)).getCanonicalFile
    val inklingHome = Util.optFileProperty(homeProperty).map(_.getCanonicalFile)

    val sbtInterface = optLibOrEmpty(inklingHome, "sbt-interface.jar")
    val compilerInterfaceSrc = optLibOrEmpty(inklingHome, "compiler-interface-sources.jar")

    val scalaCompiler = optLibOrEmpty(inklingHome, "scala-compiler.jar")
    val scalaLibrary = optLibOrEmpty(inklingHome, "scala-library.jar")

    val cacheLimit = Util.intProperty(prop("cache.limit"), 5)
    val loggerCacheLimit = Util.intProperty(prop("logger.cache.limit"), cacheLimit)
    val compilerCacheLimit = Util.intProperty(prop("compiler.cache.limit"), cacheLimit)
    val analysisCacheLimit = Util.intProperty(prop("analysis.cache.limit"), cacheLimit)

    def prop(name: String) = Command + "." + name
  }

  def optLib(homeDir: Option[File], name: String): Option[File] = {
    homeDir flatMap { home =>
      val lib = home / "lib" / name
      if (lib.exists) Some(lib) else None
    }
  }

  def optLibOrEmpty(homeDir: Option[File], name: String): File = optLib(homeDir, name) getOrElse new File("")

  case class Version(published: String, timestamp: String, commit: String)

  lazy val inklingVersion: Version = {
    val props = Util.propertiesFromResource("inkling.version.properties", getClass.getClassLoader)
    Version(
      props.getProperty("version", "unknown"),
      props.getProperty("timestamp", ""),
      props.getProperty("commit", "")
    )
  }

  lazy val versionString: String = {
    import inklingVersion._
    if (published.endsWith("-SNAPSHOT")) "%s %s-%s" format (published, timestamp, commit take 10)
    else published
  }

  def printVersion(): Unit = println("%s (%s) %s" format (Command, Description, versionString))

  def show(setup: Setup, output: String => Unit): Unit = {
    import setup._
    val values = Seq(
      "scala compiler" -> scalaCompiler,
      "scala library" -> scalaLibrary,
      "sbt interface" -> sbtInterface,
      "compiler interface sources" -> compilerInterfaceSrc,
      "java home" -> javaHome,
      "cache directory" -> cacheDir,
      "resident compiler limit" -> maxCompilers)
    Util.show(("setup", values), output)
  }
}
