// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.zinc.logging

import scala.collection.mutable
import xsbti.{ F0, Logger, Severity }

class TestLogger() extends Logger {
  def debug(msg: F0[String]): Unit = {}
  def warn(msg: F0[String]): Unit = log(Severity.Warn, msg)
  def info(msg: F0[String]): Unit = log(Severity.Info, msg)
  def error(msg: F0[String]): Unit = log(Severity.Error, msg)
  def trace(msg: F0[Throwable]): Unit = {}

  private[this] val output = mutable.HashMap[Severity, StringBuilder]()
  private[this] def log(severity: Severity, msg: F0[String]): Unit =
    output.getOrElseUpdate(severity, new StringBuilder).append(msg())

  def getOutput(severity: Severity): String = output.get(severity).map(_.toString).getOrElse("")
}
