/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File

import scala.compat.java8.OptionConverters._

import sbt.util.Level
import sbt.internal.inc.IncrementalCompilerImpl
import xsbti.CompileFailed
import xsbti.compile.{
  PreviousResult
}
import org.pantsbuild.zinc.logging.Loggers

/**
 * Command-line main class.
 */
object Main {
  val Command     = "zinc"
  val Description = "scala incremental compiler"

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

  def main(args: Array[String]): Unit = run(args, None)

  /**
   * Compile run. Current working directory can be provided (for nailed zinc).
   */
  def run(args: Array[String], cwd: Option[File]): Unit = {
    val startTime = System.currentTimeMillis

    val Parsed(rawSettings, residual, errors) = Settings.parse(args)

    // normalise relative paths to the current working directory (if provided)
    val settings = Settings.normaliseRelative(rawSettings, cwd)

    val log = Loggers.create(settings.consoleLog.logLevel, settings.consoleLog.color)
    val isDebug = settings.consoleLog.logLevel <= Level.Debug

    // bail out on any command-line option errors
    if (errors.nonEmpty) {
      for (error <- errors) log.error(error)
      log.error("See %s -help for information about options" format Command)
      sys.exit(1)
    }

    if (settings.version) printVersion()

    if (settings.help) Settings.printUsage(Command)

    // if there are no sources provided, print outputs based on current analysis if requested,
    // else print version and usage by default
    if (settings.sources.isEmpty) {
      if (!settings.version && !settings.help) {
        printVersion()
        Settings.printUsage(Command)
        sys.exit(1)
      }
      sys.exit(0)
    }

    // Load the existing analysis for the destination, if any.
    // TODO: Noisy in this method. Should factor out the "analysisStore is open" section.
    val targetAnalysisStore = AnalysisMap.cachedStore(settings.cacheFile)
    val inputs = {
      val (previousAnalysis, previousSetup) =
        targetAnalysisStore.get().map {
          case (a, s) => (Some(a), Some(s))
        } getOrElse {
          (None, None)
        }
      InputUtils.create(
        settings,
        new PreviousResult(previousAnalysis.asJava, previousSetup.asJava),
        log
      )
    }

    if (isDebug) {
      log.debug(s"Inputs: $inputs")
    }

    try {
      // Run the compile.
      val result = new IncrementalCompilerImpl().compile(inputs, log)

      // Store the output if the result changed.
      if (result.hasModified) {
        targetAnalysisStore.set(result.analysis, result.setup)
      }

      log.info("Compile success " + Util.timing(startTime))
    } catch {
      case e: CompileFailed =>
        log.error("Compile failed " + Util.timing(startTime))
        sys.exit(1)
      case e: Exception =>
        if (isDebug) e.printStackTrace
        val message = e.getMessage
        if (message ne null) log.error(message)
        sys.exit(1)
    }
  }
}
