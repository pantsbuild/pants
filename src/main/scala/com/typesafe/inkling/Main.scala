/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import java.io.File
import sbt.inc.Analysis
import sbt.Level
import xsbti.CompileFailed

object Main {
  val compilerCache = Cache[Setup, Compiler](Setup.Defaults.compilerCacheLimit)

  def main(args: Array[String]): Unit = run(args, None)

  def run(args: Array[String], cwd: Option[File]): Unit = {
    val startTime = System.currentTimeMillis

    val Parsed(rawSettings, residual, errors) = Settings.parse(args)
    val settings = Settings.normalise(rawSettings, cwd)

    if (cwd.isDefined) Util.setProperties(settings.properties)

    val log = Util.logger(settings.quiet, settings.logLevel)
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
      log.error("Need %s property to be defined" format Setup.HomeProperty)
      sys.exit(1)
    }

    val setup = Setup(settings)
    val inputs = Inputs(settings)

    if (isDebug) {
      val debug: String => Unit = log.debug(_)
      Setup.show(setup, debug)
      Inputs.show(inputs, debug)
    }

    try {
      val compiler = compilerCache.get(setup)(Compiler(setup, log))
      log.debug("compiler = %s [%s]" format (compiler, compiler.hashCode.toHexString))
      compiler.compile(inputs)
      log.info("Compile success " + Util.timing(startTime))
    } catch {
      case e: CompileFailed =>
        log.error("Compile failed " + Util.timing(startTime))
    }
  }
}
