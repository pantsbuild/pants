/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 * Copyright (C) 2015 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.logging

import java.io.{ BufferedOutputStream, File, FileOutputStream, PrintWriter }

import sbt.util.{ Level, Logger }

import sbt.internal.util.{ ConsoleLogger, ConsoleOut }

object Loggers {
  /** Create a new console logger based on level and color settings. */
  def create(
    level: Level.Value,
    color: Boolean,
    out: ConsoleOut = ConsoleOut.systemOut
  ): Logger = {
    val cl = ConsoleLogger(out, useColor = ConsoleLogger.formatEnabled && color)
    cl.setLevel(level)
    cl
  }
}
