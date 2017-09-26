/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.compiler

import java.io.File
import java.util.{ List => JList }
import scala.collection.JavaConverters._

import sbt.io.syntax._
import sbt.util.Logger

/**
 * All identity-affecting options for a zinc compiler. All fields in this struct
 * must have a useful definition of equality.
 */
case class CompilerCacheKey(
  scalaCompiler: File,
  scalaLibrary: File,
  scalaExtra: Seq[File],
  compilerBridgeSrc: File,
  compilerInterface: File,
  javaHome: Option[File],
  cacheDir: File)

object CompilerCacheKey {

  /**
   * Create compiler setup from command-line settings.
   */
  def apply(settings: Settings): CompilerCacheKey = {
    val scalaJars = InputUtils.selectScalaJars(settings.scala)
    val (compilerBridgeSrc, compilerInterface) = settings.sbt.jars
    setup(
      scalaJars.compiler,
      scalaJars.library,
      scalaJars.extra,
      compilerBridgeSrc,
      compilerInterface,
      settings.javaHome,
      settings.zincCacheDir
    )
  }

  /**
   * Create normalised and defaulted CompilerCacheKey.
   */
  def setup(
    scalaCompiler: File,
    scalaLibrary: File,
    scalaExtra: Seq[File],
    compilerBridgeSrc: File,
    compilerInterface: File,
    javaHomeDir: Option[File],
    cacheDir: File
  ): CompilerCacheKey = {
    val normalise: File => File = { _.getAbsoluteFile }
    val compilerJar          = normalise(scalaCompiler)
    val libraryJar           = normalise(scalaLibrary)
    val extraJars            = scalaExtra map normalise
    val compilerBridgeJar    = normalise(compilerBridgeSrc)
    val compilerInterfaceJar = normalise(compilerInterface)
    val javaHome             = javaHomeDir map normalise
    CompilerCacheKey(compilerJar, libraryJar, extraJars, compilerBridgeJar, compilerInterfaceJar, javaHome, cacheDir)
  }
}
