/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.zinc

import java.io.File
import sbt.inc.Analysis
import sbt.Level
import xsbti.CompileFailed

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

    val log = Util.logger(settings.quiet, settings.logLevel, settings.color)
    val isDebug = (!settings.quiet && settings.logLevel == Level.Debug)

    // bail out on any command-line option errors
    if (!errors.isEmpty) {
      for (error <- errors) log.error(error)
      log.error("See %s -help for information about options" format Setup.Command)
      sys.exit(1)
    }

    if (settings.version) Setup.printVersion()

    if (settings.help) Settings.printUsage()

    // if there are no sources provided, print version and usage by default
    if (settings.sources.isEmpty) {
      if (!settings.version && !settings.help) {
        Setup.printVersion()
        Settings.printUsage()
      }
      sys.exit(1)
    }

    // we need some of the jars in zinc home, always needs to be provided
    if (Setup.Defaults.zincHome.isEmpty) {
      log.error("Need %s property to be defined" format Setup.HomeProperty)
      sys.exit(1)
    }

    val setup = Setup(settings)
    val inputs = Inputs(settings)

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
      compiler.compile(inputs)(log)
      log.info("Compile success " + Util.timing(startTime))
    } catch {
      case e: CompileFailed =>
        log.error("Compile failed " + Util.timing(startTime))
        sys.exit(1)
    }
  }
}
