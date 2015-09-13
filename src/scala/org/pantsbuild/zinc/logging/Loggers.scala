/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 * Copyright (C) 2015 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.logging

import java.io.{ BufferedOutputStream, File, FileOutputStream, PrintWriter }
import sbt.{ AbstractLogger, ConsoleLogger, FullLogger, ConsoleOut, Level, Logger, MultiLogger }

object Loggers {
  /**
   * Create a new console logger based on level and color settings. If captureLog is
   * specified, a compound logger is created that will additionally log all output (unfiltered)
   * to a file.
   */
  def create(
    level: Level.Value,
    color: Boolean,
    out: ConsoleOut = ConsoleOut.systemOut,
    captureLog: Option[File] = None
  ): Logger = {
    // log to the console at the configured levels
    val consoleLogger = {
      val cl = ConsoleLogger(out, useColor = ConsoleLogger.formatEnabled && color)
      cl.setLevel(level)
      cl
    }
    // if a capture log was specified, add it as an additional destination
    captureLog.map { captureLogFile =>
      // NB: we append to the capture log, in order to record the complete history of a compile
      val fileLogger = {
        val fl = new FullLogger(new FileLogger(captureLogFile, true))
        fl.setLevel(Level.Debug)
        fl
      }
      new MultiLogger(List(consoleLogger, fileLogger))
    }.getOrElse {
      consoleLogger
    }
  }
}

/**
 * A logger for an output file.
 *
 * TODO: The sbt logging interface doesn't expose `close`, so this flushes for every
 * line to avoid dropping output on shutdown.
 */
class FileLogger(file: File, append: Boolean) extends Logger {
  private val out = new PrintWriter(new BufferedOutputStream(new FileOutputStream(file, append)))

  override def log(level: Level.Value, msg: => String): Unit = {
    out.println(s"[${level}]\t${msg}")
    out.flush()
  }

  def success(message: => String): Unit =
    log(Level.Info, message)

  def trace(t: => Throwable): Unit = ()
}
