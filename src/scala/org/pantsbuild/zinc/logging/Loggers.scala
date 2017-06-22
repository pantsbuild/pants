/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 * Copyright (C) 2015 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.logging

import java.io.{ BufferedOutputStream, File, FileOutputStream, PrintWriter }

import sbt.util.{ Level, LogExchange }

import sbt.internal.util.{ ConsoleOut, ManagedLogger }

object Loggers {
  /**
   * Create a new console logger based on level and color settings.
   *
   * TODO: The `ManagedLogger` API is inscrutable, so no clear way to use those
   *
   */
  def create(
    level: Level.Value,
    color: Boolean,
    out: ConsoleOut = ConsoleOut.systemOut
  ): ManagedLogger =
    LogExchange.logger("")
}
