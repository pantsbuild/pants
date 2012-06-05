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
  log: xsbti.Logger)

object Setup {
  val Command = "inkling"
  val Description = "scala incremental compiler"

  def apply(settings: Settings, log: xsbti.Logger): Setup = {
    import settings._
    val compiler = chooseScalaCompiler(scalaCompiler, scalaHome)
    val library = chooseScalaLibrary(scalaLibrary, scalaHome)
    val cacheDir = Defaults.inklingDir / inklingVersion.published
    Setup(compiler, library, Defaults.sbtInterface, Defaults.compilerInterfaceSrc, javaHome, cacheDir, residentLimit, log)
  }

  def chooseScalaCompiler(userSet: Option[File], scalaHome: Option[File]) = {
    userSet orElse optLib(scalaHome, "scala-compiler.jar") getOrElse Defaults.scalaCompiler
  }

  def chooseScalaLibrary(userSet: Option[File], scalaHome: Option[File]) = {
    userSet orElse optLib(scalaHome, "scala-library.jar") getOrElse Defaults.scalaLibrary
  }

  object Defaults {
    val dirProperty = Command + ".dir"
    val homeProperty = Command + ".home"

    val userHome = fileProperty("user.home")
    val inklingDir = optFileProperty(dirProperty).getOrElse(userHome / ("." + Command)).getCanonicalFile
    val inklingHome = optFileProperty(homeProperty).map(_.getCanonicalFile)

    val sbtInterface = optLibOrEmpty(inklingHome, "sbt-interface.jar")
    val compilerInterfaceSrc = optLibOrEmpty(inklingHome, "compiler-interface-sources.jar")

    val scalaCompiler = optLibOrEmpty(inklingHome, "scala-compiler.jar")
    val scalaLibrary = optLibOrEmpty(inklingHome, "scala-library.jar")
  }

  def fileProperty(name: String): File = new File(System.getProperty(name, ""))

  def optFileProperty(name: String): Option[File] = Option(System.getProperty(name, null)).map(new File(_))

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
