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
  forceClean: Boolean,
  definesClass: File => String => Boolean,
  javaOnly: Boolean,
  compileOrder: CompileOrder,
  outputRelations: Option[File],
  outputProducts: Option[File],
  mirrorAnalysis: Boolean)

object Inputs {
  /**
   * Create inputs based on command-line settings.
   */
  def apply(settings: Settings): Inputs = {
    import settings._
    inputs(
      classpath,
      sources,
      classesDirectory,
      scalacOptions,
      javacOptions,
      analysis.cache,
      analysis.cacheMap,
      analysis.forceClean,
      javaOnly,
      compileOrder,
      analysis.outputRelations,
      analysis.outputProducts,
      analysis.mirrorAnalysis)
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
    forceClean: Boolean,
    javaOnly: Boolean,
    compileOrder: CompileOrder,
    outputRelations: Option[File],
    outputProducts: Option[File],
    mirrorAnalysis: Boolean): Inputs =
  {
    val normalise: File => File = { _.getCanonicalFile }
    val cp               = classpath map normalise
    val srcs             = sources map normalise
    val classes          = normalise(classesDirectory)
    val cacheFile        = normalise(analysisCache.getOrElse(defaultCacheLocation(classesDirectory)))
    val upstreamAnalysis = analysisCacheMap map { case (k, v) => (normalise(k), normalise(v)) }
    val analysisMap      = (cp map { file => (file, analysisFor(file, classes, upstreamAnalysis)) }).toMap
    val printRelations   = outputRelations map normalise
    val printProducts    = outputProducts map normalise
    new Inputs(cp, srcs, classes, scalacOptions, javacOptions, cacheFile, analysisMap, forceClean, Locate.definesClass, javaOnly, compileOrder, printRelations, printProducts, mirrorAnalysis)
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
    compileOrder: String,
    mirrorAnalysisCache: Boolean): Inputs =
  inputs(
    classpath.asScala,
    sources.asScala,
    classesDirectory,
    scalacOptions.asScala,
    javacOptions.asScala,
    Option(analysisCache),
    analysisMap.asScala.toMap,
    forceClean = false,
    javaOnly = false,
    Settings.compileOrder(compileOrder),
    outputRelations = None,
    outputProducts = None,
    mirrorAnalysis = mirrorAnalysisCache
  )

  /**
   * By default the cache location is relative to the classes directory (for example, target/classes/../cache/classes).
   * If not writable then the fallback is within the zinc cache directory.
   */
  def defaultCacheLocation(classesDir: File) = {
    val alongside = classesDir.getParentFile / "cache" / classesDir.getName
    if (Util.checkWritable(alongside)) alongside
    else Setup.zincCacheDir / "analysis-cache" / classesDir.getCanonicalPath
  }

  /**
   * Get the possible cache location for a classpath entry. Checks the upstream analysis map
   * for the cache location, otherwise uses the default location for output directories.
   */
  def cacheFor(file: File, exclude: File, mapped: Map[File, File]): Option[File] = {
    if (file == exclude) None else mapped.get(file) orElse {
      if (file.isDirectory) Some(defaultCacheLocation(file)) else None
    }
  }

  /**
   * Get the analysis for a compile run, based on a classpath entry.
   * If not cached in memory, reads from the cache file.
   */
  def analysisFor(file: File, exclude: File, mapped: Map[File, File]): Analysis = {
    cacheFor(file, exclude, mapped) map Compiler.analysis getOrElse Analysis.Empty
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
      "classpath"        -> classpath,
      "sources"          -> sources,
      "output directory" -> classesDirectory,
      "scalac options"   -> scalacOptions,
      "javac options"    -> javacOptions,
      "cache file"       -> cacheFile,
      "analysis map"     -> analysisMap,
      "force clean"      -> forceClean,
      "java only"        -> javaOnly,
      "compile order"    -> compileOrder,
      "output relations" -> outputRelations,
      "output products"  -> outputProducts)
    Util.show(("Inputs", values), output)
  }
}
