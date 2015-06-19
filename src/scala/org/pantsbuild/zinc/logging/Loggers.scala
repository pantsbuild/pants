/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.logging

import java.io.File
import sbt.{ AbstractLogger, BasicLogger, ConsoleLogger, ConsoleOut, Level, Logger, MultiLogger }
import scala.util.matching.Regex

object Loggers {

  /**
   * Create a new console logger based on level, color, and filter settings. If captureLog is
   * specified, a compound logger is created that will additionally log all output (unfiltered)
   * to a file.
   */
  def logger(level: Level.Value, color: Boolean, filters: Seq[Regex], captureLog: Option[File]): Logger = {
    // log to the console at the configured levels
    val out = ConsoleOut.systemOut
    val consoleLogger = {
      val cl = ConsoleLogger(out, useColor = ConsoleLogger.formatEnabled && color)
      cl.setLevel(level)
      cl
    }
    // add filtering if defined
    val filteredLogger =
      if (filters.nonEmpty) {
        new RegexFilterLogger(consoleLogger, level, filters)
      } else {
        consoleLogger
      }
    // if a capture log was specified, add it as an additional unfiltered destination
    captureLog.map { captureLogFile =>
      new MultiLogger(List[AbstractLogger](filteredLogger, new FileLogger(captureLogFile)))
    }.getOrElse {
      filteredLogger
    }
  }
}

/**
 * A logger for an output file.
 */
class FileLogger(file: File) extends BasicLogger {
  def control(event: sbt.ControlEvent.Value,message: => String): Unit = ???
  def logAll(events: Seq[sbt.LogEvent]): Unit = ???
  def log(level: sbt.Level.Value, message: => String): Unit = ???
  def success(message: => String): Unit = ???
  def trace(t: => Throwable): Unit = ???
}

class RegexFilterLogger(underlying: Logger, level: Level.Value, filters: Seq[Regex]) extends BasicLogger {
  def control(event: sbt.ControlEvent.Value,message: => String): Unit = ???
  def logAll(events: Seq[sbt.LogEvent]): Unit = ???

  override def log(level: Level.Value, msg: => String): Unit = {
    // only apply filters if there is a chance that the underlying logger will try to log this
    if (level.id >= this.level.id) {
      val message = msg
      if (!filters.exists(_.findFirstIn(message).isDefined)) {
        underlying.log(level, message)
      }
    }
  }
  def success(message: => String): Unit = ???
  def trace(t: => Throwable): Unit = ???
}
