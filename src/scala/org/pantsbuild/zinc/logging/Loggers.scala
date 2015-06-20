/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.logging

import java.io.{ File, PrintWriter }
import sbt.{ AbstractLogger, ConsoleLogger, FullLogger, ConsoleOut, Level, Logger, MultiLogger }
import scala.util.matching.Regex

object Loggers {
  /**
   * Create a new console logger based on level, color, and filter settings. If captureLog is
   * specified, a compound logger is created that will additionally log all output (unfiltered)
   * to a file.
   */
  def create(level: Level.Value, color: Boolean, filters: Seq[Regex], captureLog: Option[File]): Logger = {
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
        new FullLogger(new RegexFilterLogger(consoleLogger, filters))
      } else {
        consoleLogger
      }
    // if a capture log was specified, add it as an additional unfiltered destination
    captureLog.map { captureLogFile =>
      new MultiLogger(
        List(
          filteredLogger,
          new FullLogger(new UnfilteredFileLogger(captureLogFile))
        )
      )
    }.getOrElse {
      filteredLogger
    }
  }
}

/**
 * An unfiltered logger for an output file (no Level.)
 */
class UnfilteredFileLogger(file: File) extends Logger {
  private val out = new PrintWriter(file)

  override def log(level: Level.Value, msg: => String): Unit = {
    out.println(s"[${level}]\t${msg}")
    out.flush()
  }

  def success(message: => String): Unit =
    log(Level.Info, message)

  def trace(t: => Throwable): Unit = ()
}

class RegexFilterLogger(underlying: AbstractLogger, filters: Seq[Regex]) extends Logger {
  override def log(level: Level.Value, msg: => String): Unit = {
    // only apply filters if there is a chance that the underlying logger will try to log this
    if (level.id >= underlying.getLevel.id) {
      val message = msg
      if (!filters.exists(_.findFirstIn(message).isDefined)) {
        underlying.log(level, message)
      }
    }
  }

  def success(message: => String): Unit =
    underlying.success(message)

  def trace(t: => Throwable): Unit =
    underlying.trace(t)
}
