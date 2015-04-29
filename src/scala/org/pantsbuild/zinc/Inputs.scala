/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import java.util.{List => JList, Map => JMap}

import sbt.Path._
import sbt.inc.{Analysis, Locate}
import xsbti.compile.CompileOrder

import scala.collection.JavaConverters._

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
    incOptions: IncOptions,
    outputRelations: Option[File],
    outputProducts: Option[File],
    mirrorAnalysis: Boolean)

object Inputs {
  /**
   * Create inputs based on command-line settings.
   */
  def apply(settings: Settings): Inputs = {
    inputs(
      settings.classpath,
      settings.sources,
      settings.classesDirectory,
      settings.scalacOptions,
      settings.javacOptions,
      settings.analysis.cache,
      settings.analysis.cacheMap,
      settings.analysis.forceClean,
      settings.javaOnly,
      settings.compileOrder,
      settings.incOptions,
      settings.analysis.outputRelations,
      settings.analysis.outputProducts,
      settings.analysis.mirrorAnalysis)
  }
  @deprecated("Use the variant that takes `incOptions` parameter, instead.", "0.3.5.3")
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
    create(classpath, sources, classesDirectory, scalacOptions, javacOptions,
      analysisCache, analysisMap, compileOrder, IncOptions(), mirrorAnalysisCache)
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
      incOptions: IncOptions,
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
      incOptions,
      outputRelations = None,
      outputProducts = None,
      mirrorAnalysis = mirrorAnalysisCache
    )
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
      incOptions: IncOptions,
      outputRelations: Option[File],
      outputProducts: Option[File],
      mirrorAnalysis: Boolean): Inputs = {
    val normalise: File => File = {
      _.getAbsoluteFile
    }
    val cp = classpath map normalise
    val srcs = sources map normalise
    val classes = normalise(classesDirectory)
    val cacheFile = normalise(analysisCache.getOrElse(defaultCacheLocation(classesDirectory)))
    val upstreamAnalysis = analysisCacheMap map { case (k, v) => (normalise(k), normalise(v)) }
    val analysisMap = (cp map { file => (file, analysisFor(file, classes, upstreamAnalysis)) }).toMap
    val incOpts = updateIncOptions(incOptions, classesDirectory, normalise)
    val printRelations = outputRelations map normalise
    val printProducts = outputProducts map normalise
    new Inputs(
      cp, srcs, classes, scalacOptions, javacOptions, cacheFile, analysisMap, forceClean, Locate.definesClass,
      javaOnly, compileOrder, incOpts, printRelations, printProducts, mirrorAnalysis
    )
  }
  /**
   * By default the cache location is relative to the classes directory (for example, target/classes/../cache/classes).
   */
  def defaultCacheLocation(classesDir: File) = {
    classesDir.getParentFile / "cache" / classesDir.getName
  }
  /**
   * Get the analysis for a compile run, based on a classpath entry.
   * If not cached in memory, reads from the cache file.
   */
  def analysisFor(file: File, exclude: File, mapped: Map[File, File]): Analysis = {
    cacheFor(file, exclude, mapped) map Compiler.analysis getOrElse Analysis.Empty
  }
  /**
   * Get the possible cache location for a classpath entry. Checks the upstream analysis map
   * for the cache location, otherwise uses the default location for output directories.
   */
  def cacheFor(file: File, exclude: File, mapped: Map[File, File]): Option[File] = {
    mapped.get(file) orElse {
      if (file.isDirectory && file != exclude) Some(defaultCacheLocation(file)) else None
    }
  }
  /**
   * Normalise files and default the backup directory.
   */
  def updateIncOptions(incOptions: IncOptions, classesDir: File, normalise: File => File): IncOptions = {
    incOptions.copy(
      apiDumpDirectory = incOptions.apiDumpDirectory map normalise,
      backup = getBackupDirectory(incOptions, classesDir, normalise)
    )
  }

  /**
   * Get normalised, default if not specified, backup directory. If transactional.
   */
  def getBackupDirectory(incOptions: IncOptions, classesDir: File, normalise: File => File): Option[File] = {
    if (incOptions.transactional)
      Some(normalise(incOptions.backup.getOrElse(defaultBackupLocation(classesDir))))
    else
      None
  }

  /**
   * By default the backup location is relative to the classes directory (for example, target/classes/../backup/classes).
   */
  def defaultBackupLocation(classesDir: File) = {
    classesDir.getParentFile / "backup" / classesDir.getName
  }

  /**
   * Verify inputs and update if necessary.
   * Currently checks that the cache file is writable.
   */
  def verify(inputs: Inputs): Inputs = {
    inputs.copy(cacheFile = verifyCacheFile(inputs.cacheFile, inputs.classesDirectory))
  }

  /**
   * Check that the cache file is writable.
   * If not writable then the fallback is within the zinc cache directory.
   *
   */
  def verifyCacheFile(cacheFile: File, classesDir: File): File = {
    if (Util.checkWritable(cacheFile)) cacheFile
    else Setup.zincCacheDir / "analysis-cache" / Util.pathHash(classesDir)
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

    val incOpts = Seq(
      "transitive step" -> inputs.incOptions.transitiveStep,
      "recompile all fraction" -> inputs.incOptions.recompileAllFraction,
      "debug relations" -> inputs.incOptions.relationsDebug,
      "debug api" -> inputs.incOptions.apiDebug,
      "api dump" -> inputs.incOptions.apiDumpDirectory,
      "api diff context size" -> inputs.incOptions.apiDiffContextSize,
      "transactional" -> inputs.incOptions.transactional,
      "backup directory" -> inputs.incOptions.backup,
      "recompile on macro def" -> inputs.incOptions.recompileOnMacroDef,
      "name hashing" -> inputs.incOptions.nameHashing
    )

    val values = Seq(
      "classpath" -> inputs.classpath,
      "sources" -> inputs.sources,
      "output directory" -> inputs.classesDirectory,
      "scalac options" -> inputs.scalacOptions,
      "javac options" -> inputs.javacOptions,
      "cache file" -> inputs.cacheFile,
      "analysis map" -> inputs.analysisMap,
      "force clean" -> inputs.forceClean,
      "java only" -> inputs.javaOnly,
      "compile order" -> inputs.compileOrder,
      "incremental compiler options" -> incOpts,
      "output relations" -> inputs.outputRelations,
      "output products" -> inputs.outputProducts)

    Util.show(("Inputs", values), output)
  }
}
