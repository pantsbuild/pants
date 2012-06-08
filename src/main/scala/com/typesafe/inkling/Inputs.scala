/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import java.io.File
import sbt.compiler.IC
import sbt.inc.{ Analysis, Locate }
import sbt.Path._
import xsbti.compile.CompileOrder

case class Inputs(
  classpath: Seq[File],
  sources: Seq[File],
  classesDirectory: File,
  scalacOptions: Seq[String],
  javacOptions: Seq[String],
  cacheFile: File,
  analysisMap: Map[File, Analysis],
  definesClass: File => String => Boolean,
  javaOnly: Boolean,
  compileOrder: CompileOrder)

object Inputs {
  def apply(settings: Settings): Inputs = {
    import settings.{ scalacOptions, javacOptions, javaOnly, compileOrder }
    val classpath = settings.classpath map normalise
    val sources = settings.sources map normalise
    val classesDirectory = normalise(settings.classesDirectory)
    val cacheFile = normalise(settings.analysisCache.getOrElse(defaultCacheLocation(classesDirectory)))
    val upstreamAnalysis = settings.analysisMap map { case (k, v) => (normalise(k), normalise(v)) }
    val analysisMap = (classpath map { file => (file, analysisFor(file, classesDirectory, upstreamAnalysis)) }).toMap
    new Inputs(classpath, sources, classesDirectory, scalacOptions, javacOptions, cacheFile, analysisMap, Locate.definesClass, javaOnly, compileOrder)
  }

  def defaultCacheLocation(file: File) = file.getParentFile / "cache" / file.getName

  def analysisFor(file: File, exclude: File, mapped: Map[File, File]): Analysis = {
    if (file != exclude && file.isDirectory) {
      val cacheFile = normalise(mapped.getOrElse(file, defaultCacheLocation(file)))
      Compiler.analysisCache.get(cacheFile)(IC.readAnalysis(cacheFile))
    } else Analysis.Empty
  }

  def normalise: File => File = { _.getCanonicalFile }

  def show(inputs: Inputs, output: String => Unit): Unit = {
    import inputs._
    val values = Seq(
      "classpath" -> classpath,
      "sources" -> sources,
      "output directory" -> classesDirectory,
      "scalac options" -> scalacOptions,
      "javac options" -> javacOptions,
      "cache file" -> cacheFile,
      "analysis map" -> analysisMap,
      "java only" -> javaOnly,
      "compile order" -> compileOrder)
    Util.show(("inputs", values), output)
  }
}
