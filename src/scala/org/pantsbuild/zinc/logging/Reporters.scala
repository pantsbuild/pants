/**
 * Copyright (C) 2015 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.logging

import sbt.internal.inc.LoggerReporter
import sbt.util.Logger
import xsbti.{ Position, Reporter, Severity }

import scala.util.matching.Regex

object Reporters {
  def create(
    log: Logger,
    fileFilters: Seq[Regex],
    msgFilters: Seq[Regex],
    maximumErrors: Int = 100
  ): Reporter =
    if (fileFilters.isEmpty && msgFilters.isEmpty) {
      new LoggerReporter(maximumErrors, log)
    } else {
      new RegexFilterReporter(fileFilters, msgFilters, maximumErrors, log)
    }
}

/**
 * Extends LoggerReporter to filter compile warnings that match various patterns.
 */
class RegexFilterReporter(
  fileFilters: Seq[Regex],
  msgFilters: Seq[Regex],
  maximumErrors: Int,
  log: Logger
) extends LoggerReporter(
  maximumErrors,
  log
) {
  
  private final def isFiltered(filters: Seq[Regex], str: String): Boolean =
    filters.exists(_.findFirstIn(str).isDefined)

  private final def isFiltered(pos: Position, msg: String, severity: Severity): Boolean =
    severity != Severity.Error && (
      (!pos.sourceFile.isEmpty && isFiltered(fileFilters, pos.sourceFile.get.getPath)) || (
        isFiltered(msgFilters, msg)
      )
    )

  override def display(pos: Position, msg: String, severity: Severity): Unit =
    if (isFiltered(pos, msg, severity)) {
      // the only side-effecting operation in the superclass
      inc(severity)
    } else {
      super.display(pos, msg, severity)
    }
}
