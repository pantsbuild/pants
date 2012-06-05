/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import sbt.inc.Analysis
import sbt.Level
import xsbti.CompileFailed

object Main {
  def main(args: Array[String]): Unit = {
    val startTime = System.currentTimeMillis

    val Parsed(settings, residual, errors) = Settings.parse(args)

    val log = Util.newLogger(settings.quiet, settings.logLevel)
    val isDebug = (!settings.quiet && settings.logLevel == Level.Debug)

    if (!errors.isEmpty) {
      for (error <- errors) log.error(error)
      log.error("See %s -help for information about options" format Setup.Command)
      sys.exit(1)
    }

    if (settings.version) Setup.printVersion()

    if (settings.help) Settings.printUsage()

    if (settings.sources.isEmpty) {
      if (!settings.version && !settings.help) {
        Setup.printVersion()
        Settings.printUsage()
      }
      sys.exit(1)
    }

    if (Setup.Defaults.inklingHome.isEmpty) {
      log.error("Need %s property to be defined" format Setup.Defaults.homeProperty)
      sys.exit(1)
    }

    val setup = Setup(settings, log)
    val inputs = Inputs(settings)

    if (isDebug) {
      val debug: String => Unit = log.debug(_)
      Setup.show(setup, debug)
      Inputs.show(inputs, debug)
    }

    try {
      val compiler = Compiler(setup)
      log.debug("compiler = " + compiler)
      compiler.compile(inputs)
      log.info("Compile success " + Util.timing(startTime))
    } catch {
      case e: CompileFailed =>
        log.error("Compile failed " + Util.timing(startTime))
    }
  }
}
