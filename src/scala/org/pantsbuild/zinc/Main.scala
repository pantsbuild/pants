/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File

import scala.compat.java8.OptionConverters._

import sbt.util.Level
import xsbti.CompileFailed
import xsbti.compile.{
  PreviousResult
}
import org.pantsbuild.zinc.logging.{ Loggers, Reporters }

/**
 * Command-line main class.
 */
object Main {
  def main(args: Array[String]): Unit = run(args, None)

  /**
   * Compile run. Current working directory can be provided (for nailed zinc).
   */
  def run(args: Array[String], cwd: Option[File]): Unit = {
    val startTime = System.currentTimeMillis

    val Parsed(rawSettings, residual, errors) = Settings.parse(args)

    // normalise relative paths to the current working directory (if provided)
    val settings = Settings.normaliseRelative(rawSettings, cwd)

    // if nailed then also set any system properties provided
    if (cwd.isDefined) Util.setProperties(settings.properties)

    val log = Loggers.create(settings.consoleLog.logLevel, settings.consoleLog.color)
    val isDebug = settings.consoleLog.logLevel == Level.Debug

    // bail out on any command-line option errors
    if (errors.nonEmpty) {
      for (error <- errors) log.error(error)
      log.error("See %s -help for information about options" format Setup.Command)
      sys.exit(1)
    }

    if (settings.version) Setup.printVersion()

    if (settings.help) Settings.printUsage()

    // if there are no sources provided, print outputs based on current analysis if requested,
    // else print version and usage by default
    if (settings.sources.isEmpty) {
      if (!settings.version && !settings.help) {
        Setup.printVersion()
        Settings.printUsage()
        sys.exit(1)
      }
      sys.exit(0)
    }

    // check we have all necessary files
    if (!Setup.verify(setup, log)) {
      log.error("See %s -help for information about locating necessary files" format Setup.Command)
      sys.exit(1)
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
        log,
        settings,
        new PreviousResult(previousAnalysis.asJava, previousSetup.asJava)
      )
    }

    if (isDebug) {
      val debug: String => Unit = log.debug(_)
      Setup.show(setup, debug)
      InputUtils.show(inputs, debug)
      debug("Setup and Inputs valid " + Util.timing(startTime))
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
    } finally {
      if (settings.consoleLog.printProgress || settings.consoleLog.heartbeatSecs > 0) {
        System.out.println("Done.")
      }
    }
  }
}
