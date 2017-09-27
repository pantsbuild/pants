/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.compiler

import sbt.internal.inc.IncrementalCompilerImpl
import sbt.internal.util.{ ConsoleLogger, ConsoleOut }
import sbt.util.Level
import xsbti.CompileFailed

import org.pantsbuild.zinc.analysis.AnalysisMap
import org.pantsbuild.zinc.options.Parsed
import org.pantsbuild.zinc.util.Util

/**
 * Command-line main class.
 */
object Main {
  val Command = "zinc-compiler"
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

  def mkLogger(settings: Settings) = {
    // If someone has not explicitly enabled log4j2 JMX, disable it.
    if (!Util.isSetProperty("log4j2.disable.jmx")) {
      Util.setProperty("log4j2.disable.jmx", "true")
    }
    val cl =
      ConsoleLogger(
        out = ConsoleOut.systemOut,
        ansiCodesSupported = settings.consoleLog.color
      )
    cl.setLevel(settings.consoleLog.logLevel)
    cl
  }

  /**
   * Run a compile.
   */
  def main(args: Array[String]): Unit = {
    val startTime = System.currentTimeMillis

    val Parsed(settings, residual, errors) = Settings.parse(args)

    val log = mkLogger(settings)
    val isDebug = settings.consoleLog.logLevel <= Level.Debug

    // bail out on any command-line option errors
    if (errors.nonEmpty) {
      for (error <- errors) log.error(error)
      log.error("See %s -help for information about options" format Command)
      sys.exit(1)
    }

    if (settings.version) printVersion()

    if (settings.help) Settings.printUsage(Command, residualArgs = "<sources>")

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
    val analysisMap = AnalysisMap.create(settings.analysis)
    val (targetAnalysisStore, previousResult) =
      InputUtils.loadDestinationAnalysis(settings, analysisMap, log)
    val inputs = InputUtils.create(settings, analysisMap, previousResult, log)

    if (isDebug) {
      log.debug(s"Inputs: $inputs")
    }

    try {
      // Run the compile.
      val result = new IncrementalCompilerImpl().compile(inputs, log)

      // Store the output if the result changed.
      if (result.hasModified) {
        targetAnalysisStore.set(
          // TODO
          sbt.internal.inc.ConcreteAnalysisContents(result.analysis, result.setup)
        )
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
