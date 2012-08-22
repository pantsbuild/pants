/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.zinc

import java.io.File
import java.util.{ List => JList, Map => JMap }
import sbt.compiler.IC
import sbt.inc.{ Analysis, Locate }
import sbt.Path._
import scala.collection.JavaConverters._
import xsbti.compile.CompileOrder

/**
 * All inputs for a compile run.
 */
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
  compileOrder: CompileOrder,
  outputRelations: Option[File],
  outputProducts: Option[File])

object Inputs {
  /**
   * Create inputs based on command-line settings.
   */
  def apply(settings: Settings): Inputs = {
    import settings._
    inputs(classpath, sources, classesDirectory, scalacOptions, javacOptions, analysis.cache, analysis.cacheMap, javaOnly, compileOrder, analysis.outputRelations, analysis.outputProducts)
  }

  /**
   * Create normalised and defaulted Inputs.
   */
  def inputs(
    classpath: Seq[File],
    sources: Seq[File],
    classesDirectory: File,
    scalacOptions: Seq[String],
    javacOptions: Seq[String],
    analysisCache: Option[File],
    analysisCacheMap: Map[File, File],
    javaOnly: Boolean,
    compileOrder: CompileOrder,
    outputRelations: Option[File],
    outputProducts: Option[File]): Inputs =
  {
    val normalise: File => File = { _.getCanonicalFile }
    val cp = classpath map normalise
    val srcs = sources map normalise
    val classes = normalise(classesDirectory)
    val cacheFile = normalise(analysisCache.getOrElse(defaultCacheLocation(classesDirectory)))
    val upstreamAnalysis = analysisCacheMap map { case (k, v) => (normalise(k), normalise(v)) }
    val analysisMap = (classpath map { file => (file, analysisFor(file, classesDirectory, upstreamAnalysis)) }).toMap
    val printRelations = outputRelations map normalise
    val printProducts = outputProducts map normalise
    new Inputs(cp, srcs, classes, scalacOptions, javacOptions, cacheFile, analysisMap, Locate.definesClass, javaOnly, compileOrder, printRelations, printProducts)
  }

  /**
   * Java API for creating Inputs.
   */
  def create(
    classpath: JList[File],
    sources: JList[File],
    classesDirectory: File,
    scalacOptions: JList[String],
    javacOptions: JList[String],
    analysisCache: File,
    analysisMap: JMap[File, File],
    compileOrder: String): Inputs =
  inputs(
    classpath.asScala,
    sources.asScala,
    classesDirectory,
    scalacOptions.asScala,
    javacOptions.asScala,
    Option(analysisCache),
    analysisMap.asScala.toMap,
    javaOnly = false,
    Settings.compileOrder(compileOrder),
    outputRelations = None,
    outputProducts = None
  )

  /**
   * By default the cache location is relative to the classes directory (for example, target/classes/../cache/classes).
   */
  def defaultCacheLocation(file: File) = file.getParentFile / "cache" / file.getName

  /**
   * Get the analysis for a compile run, based on the output directory.
   * Checks the analysis map setting for the cache location, otherwise default location.
   * If not cached in memory, reads from the cache file.
   */
  def analysisFor(file: File, exclude: File, mapped: Map[File, File]): Analysis = {
    if (file != exclude && file.isDirectory) {
      val cacheFile = mapped.getOrElse(file, defaultCacheLocation(file)).getCanonicalFile
      Compiler.analysisCache.get(cacheFile)(IC.readAnalysis(cacheFile))
    } else Analysis.Empty
  }

  /**
   * Debug output for inputs.
   */
  def debug(inputs: Inputs, log: xsbti.Logger): Unit = {
    show(inputs, s => log.debug(sbt.Logger.f0(s)))
  }

  /**
   * Debug output for inputs.
   */
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
      "compile order" -> compileOrder,
      "output relations" -> outputRelations,
      "output products" -> outputProducts)
    Util.show(("Inputs", values), output)
  }
}
