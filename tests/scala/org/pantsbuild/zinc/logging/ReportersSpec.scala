// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.zinc.logging

import org.junit.runner.RunWith
import org.scalatest.junit.JUnitRunner
import org.scalatest.MustMatchers
import org.scalatest.WordSpec
import sbt.Logger
import xsbti.Severity

@RunWith(classOf[JUnitRunner])
class ReportersSpec extends WordSpec with MustMatchers {

  private val testProblem = Logger.problem(
    "unused (category)",
    Logger.position(None, "unused", None, None, None, None, None),
    "is deprecated",
    Severity.Warn
  )

  "Reporters" should {
    "convert warnings to errors with -fatal-warnings" in {
      val reporter = Reporters.create(
        new TestLogger,
        fileFilters = Seq.empty,
        msgFilters = Seq.empty,
        fatalWarnings = true,
        nonFatalWarningsPatterns = Seq.empty,
        maximumErrors = 100
      )

      reporter.log(testProblem.position, testProblem.message, testProblem.severity)

      assert(reporter.problems.length === 1)
      val observedProblem = reporter.problems()(0)
      assert(observedProblem.position === testProblem.position)
      assert(observedProblem.message === testProblem.message)
      assert(observedProblem.severity === Severity.Error)
    }

    "exempt nonFatalWarningsPatterns from fatal warnings" in {
      val reporter = Reporters.create(
        new TestLogger,
        fileFilters = Seq.empty,
        msgFilters = Seq.empty,
        fatalWarnings = true,
        nonFatalWarningsPatterns = Seq("is deprecated".r),
        maximumErrors = 100
      )

      reporter.log(testProblem.position, testProblem.message, testProblem.severity)

      assert(reporter.problems.length === 1)
      val observedProblem = reporter.problems()(0)
      assert(observedProblem.position === testProblem.position)
      assert(observedProblem.message === testProblem.message)
      assert(observedProblem.severity === Severity.Warn)
    }

    "mention one fatal warning in summary" in {
      val logger = new TestLogger
      val reporter = Reporters.create(
        logger,
        fileFilters = Seq.empty,
        msgFilters = Seq.empty,
        fatalWarnings = true,
        nonFatalWarningsPatterns = Seq.empty,
        maximumErrors = 100
      )

      reporter.log(testProblem.position, testProblem.message, testProblem.severity)
      reporter.printSummary()

      assert(logger.getOutput(Severity.Error).contains("was originally a warning"))
    }

    "grammar/pluralization in summary for multiple fatal warnings" in {
      val logger = new TestLogger
      val reporter = Reporters.create(
        logger,
        fileFilters = Seq.empty,
        msgFilters = Seq.empty,
        fatalWarnings = true,
        nonFatalWarningsPatterns = Seq.empty,
        maximumErrors = 100
      )

      reporter.log(testProblem.position, testProblem.message, testProblem.severity)
      reporter.log(testProblem.position, testProblem.message, testProblem.severity)
      reporter.printSummary()

      assert(logger.getOutput(Severity.Error).contains("two errors were originally warnings"))
    }
  }
}
