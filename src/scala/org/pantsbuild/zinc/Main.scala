/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import sbt.util.Level
import xsbti.CompileFailed
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
    val settings = Settings.normalise(rawSettings, cwd)

    // if nailed then also set any system properties provided
    if (cwd.isDefined) Util.setProperties(settings.properties)

    val log =
      Loggers.create(
        settings.consoleLog.logLevel,
        settings.consoleLog.color,
        captureLog = settings.captureLog
      )
    val isDebug = settings.consoleLog.logLevel == Level.Debug
    val reporter =
      Reporters.create(
        log,
        settings.consoleLog.fileFilters,
        settings.consoleLog.msgFilters
      )
    val progress =
      new SimpleCompileProgress(
        settings.consoleLog.logPhases,
        settings.consoleLog.printProgress,
        settings.consoleLog.heartbeatSecs
      )(log)

    // bail out on any command-line option errors
    if (errors.nonEmpty) {
      for (error <- errors) log.error(error)
      log.error("See %s -help for information about options" format Setup.Command)
      sys.exit(1)
    }

    if (settings.version) Setup.printVersion()

    if (settings.help) Settings.printUsage()

    val inputs = Inputs(log, settings)
    val setup = Setup(settings)

    // if there are no sources provided, print outputs based on current analysis if requested,
    // else print version and usage by default
    if (inputs.sources.isEmpty) {
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

    // verify inputs
    Inputs.verify(inputs)

    if (isDebug) {
      val debug: String => Unit = log.debug(_)
      Setup.show(setup, debug)
      Inputs.show(inputs, debug)
      debug("Setup and Inputs parsed " + Util.timing(startTime))
    }

    // run the compile
    try {
      val compiler = Compiler(setup, log)
      log.debug("Zinc compiler = %s [%s]" format (compiler, compiler.hashCode.toHexString))
      compiler.compile(inputs, cwd, reporter, progress)(log)
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
