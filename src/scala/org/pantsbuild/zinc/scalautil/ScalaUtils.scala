/**
 * Copyright (C) 2018 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.scalautil

import java.io.File
import sbt.io.Path
import java.net.URLClassLoader
import sbt.internal.inc.ScalaInstance
import xsbti.compile.{
  ScalaInstance => XScalaInstance
}
import org.pantsbuild.zinc.util.Util

object ScalaUtils {
  private def scalaLoader(jars: Seq[File]) =
    new URLClassLoader(
      Path.toURLs(jars),
      sbt.internal.inc.classpath.ClasspathUtilities.rootLoader
    )

  private def scalaVersion(scalaLoader: ClassLoader): Option[String] = {
    Util.propertyFromResource("compiler.properties", "version.number", scalaLoader)
  }

  def scalaInstance(scalaCompiler: File, scalaExtra: Seq[File], scalaLibrary: File): XScalaInstance = {
    val allJars = scalaLibrary +: scalaCompiler +: scalaExtra
    val allJarsLoader = scalaLoader(allJars)
    val libraryOnlyLoader = scalaLoader(scalaLibrary +: scalaExtra)
    new ScalaInstance(
      scalaVersion(allJarsLoader).getOrElse("unknown"),
      allJarsLoader,
      libraryOnlyLoader,
      scalaLibrary,
      scalaCompiler,
      allJars.toArray,
      None
    )
  }
}
