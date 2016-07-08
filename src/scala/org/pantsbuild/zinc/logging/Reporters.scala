/**
 * Copyright (C) 2015 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.logging

import xsbti.{ Position, Reporter, Severity }
import sbt.{ Logger, LoggerReporter }

import scala.util.matching.Regex

object Reporters {
  def create(
    log: Logger,
    fileFilters: Seq[Regex],
    msgFilters: Seq[Regex],
    fatalWarnings: Boolean,
    nonFatalWarningsPatterns: Seq[Regex],
    maximumErrors: Int = 100
  ): Reporter =
    if (fileFilters.isEmpty && msgFilters.isEmpty && nonFatalWarningsPatterns.isEmpty && !fatalWarnings) {
      new LoggerReporter(maximumErrors, log)
    } else {
      new RegexFilterReporter(fileFilters, msgFilters, fatalWarnings, nonFatalWarningsPatterns, maximumErrors, log)
    }
}

/**
 * Extends LoggerReporter to filter compile warnings that match various patterns.
 */
class RegexFilterReporter(
  fileFilters: Seq[Regex],
  msgFilters: Seq[Regex],
  fatalWarnings: Boolean,
  nonFatalWarningsPatterns: Seq[Regex],
  maximumErrors: Int,
  log: Logger
) extends LoggerReporter(
  maximumErrors,
  log
) {

  private var fatalWarningsEncountered = 0
  override def reset(): Unit = {
    fatalWarningsEncountered = 0
    super.reset()
  }

  private final def isFiltered(filters: Seq[Regex], str: String): Boolean =
    filters.exists(_.findFirstIn(str).isDefined)

  private final def isFiltered(pos: Position, msg: String, severity: Severity): Boolean =
    severity != Severity.Error && (
      (!pos.sourceFile.isEmpty && isFiltered(fileFilters, pos.sourceFile.get.getPath)) || (
        isFiltered(msgFilters, msg)
      )
    )

  private final def isFatalWarning(msg: String, severity: Severity): Boolean =
    fatalWarnings && severity == Severity.Warn && !isFiltered(nonFatalWarningsPatterns, msg)

  override def display(pos: Position, msg: String, severity: Severity): Unit =
    if (isFiltered(pos, msg, severity)) {
      // the only side-effecting operation in the superclass
      inc(severity)
    } else {
      super.display(pos, msg, severity)
    }

  override def log(pos: Position, msg: String, severity: Severity): Unit = {
    if (isFatalWarning(msg, severity)) {
      fatalWarningsEncountered += 1
      super.log(pos, msg, Severity.Error)
    } else {
      super.log(pos, msg, severity)
    }
  }

  override def printSummary(): Unit = {
    super.printSummary()
    if (fatalWarningsEncountered > 0) {
      val errorString = LoggerReporter.countElementsAsString(fatalWarningsEncountered, "error")
      val warningString = if (fatalWarningsEncountered == 1)
        "was originally a warning"
      else
        "were originally warnings"
      log.error(s"($errorString $warningString -- -fatal-warnings enabled)")
    }
  }
}
