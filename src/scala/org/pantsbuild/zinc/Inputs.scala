/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import java.util.{ List => JList, Map => JMap }

import sbt.Logger
import sbt.Path._
import sbt.compiler.IC
import sbt.inc.{ Analysis, Locate, ZincPrivateAnalysis }
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
  analysisMap: AnalysisMap,
  javaOnly: Boolean,
  compileOrder: CompileOrder,
  incOptions: IncOptions)

object Inputs {
  /**
   * Create inputs based on command-line settings.
   */
  def apply(log: Logger, settings: Settings): Inputs = {
    import settings._
    inputs(
      log,
      classpath,
      sources,
      classesDirectory,
      scalacOptions,
      javacOptions,
      analysis.cache,
      analysis.cacheMap,
      javaOnly,
      compileOrder,
      incOptions)
  }

  /**
   * Create normalised and defaulted Inputs.
   */
  def inputs(
    log: Logger,
    classpath: Seq[File],
    sources: Seq[File],
    classesDirectory: File,
    scalacOptions: Seq[String],
    javacOptions: Seq[String],
    analysisCache: Option[File],
    analysisCacheMap: Map[File, File],
    javaOnly: Boolean,
    compileOrder: CompileOrder,
    incOptions: IncOptions): Inputs =
  {
    val normalise: File => File = { _.getAbsoluteFile }
    val cp = classpath map normalise
    val srcs = sources map normalise
    val classes = normalise(classesDirectory)
    val cacheFile = normalise(analysisCache.getOrElse(defaultCacheLocation(classesDirectory)))
    val analysisMap =
      AnalysisMap.create(
        analysisCacheMap.collect {
          case (k, v) if normalise(k) != classes =>
            (normalise(k), normalise(v))
        },
        log
      )
    val incOpts = updateIncOptions(incOptions, classesDirectory, normalise)
    new Inputs(
      cp, srcs, classes, scalacOptions, javacOptions, cacheFile, analysisMap,
      javaOnly, compileOrder, incOpts
    )
  }

  /**
   * Java API for creating Inputs.
   */
  def create(
    log: Logger,
    classpath: JList[File],
    sources: JList[File],
    classesDirectory: File,
    scalacOptions: JList[String],
    javacOptions: JList[String],
    analysisCache: File,
    analysisMap: JMap[File, File],
    compileOrder: String,
    incOptions: IncOptions): Inputs =
  inputs(
    log,
    classpath.asScala,
    sources.asScala,
    classesDirectory,
    scalacOptions.asScala,
    javacOptions.asScala,
    Option(analysisCache),
    analysisMap.asScala.toMap,
    javaOnly = false,
    Settings.compileOrder(compileOrder),
    incOptions
  )

  /**
   * By default the cache location is relative to the classes directory (for example, target/classes/../cache/classes).
   */
  def defaultCacheLocation(classesDir: File) = {
    classesDir.getParentFile / "cache" / classesDir.getName
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
    import inputs._

    val incOpts = Seq(
      "transitive step"        -> incOptions.transitiveStep,
      "recompile all fraction" -> incOptions.recompileAllFraction,
      "debug relations"        -> incOptions.relationsDebug,
      "debug api"              -> incOptions.apiDebug,
      "api dump"               -> incOptions.apiDumpDirectory,
      "api diff context size"  -> incOptions.apiDiffContextSize,
      "transactional"          -> incOptions.transactional,
      "backup directory"       -> incOptions.backup,
      "recompile on macro def" -> incOptions.recompileOnMacroDef,
      "name hashing"           -> incOptions.nameHashing
    )

    val values = Seq(
      "classpath"                    -> classpath,
      "sources"                      -> sources,
      "output directory"             -> classesDirectory,
      "scalac options"               -> scalacOptions,
      "javac options"                -> javacOptions,
      "cache file"                   -> cacheFile,
      "analysis map"                 -> analysisMap,
      "java only"                    -> javaOnly,
      "compile order"                -> compileOrder,
      "incremental compiler options" -> incOpts)

    Util.show(("Inputs", values), output)
  }
}
