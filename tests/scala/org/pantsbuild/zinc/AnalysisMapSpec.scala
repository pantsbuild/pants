// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.zinc

import sbt.io.IO
import sbt.internal.util.{
  ConsoleLogger,
  ConsoleOut
}

import org.junit.runner.RunWith
import org.scalatest.WordSpec
import org.scalatest.junit.JUnitRunner
import org.scalatest.MustMatchers

@RunWith(classOf[JUnitRunner])
class AnalysisMapSpec extends WordSpec with MustMatchers {
  "AnalysisMap" should {
    "succeed for empty analysis" in {
      IO.withTemporaryDirectory { classpathEntry =>
        val am = AnalysisMap.create(Map(), ConsoleLogger(ConsoleOut.systemOut))
        val dc = am.getPCELookup.definesClass(classpathEntry)
        dc("NonExistent.class") must be(false)
      }
    }
    // TODO: needs more testing with spoofed analysis
  }
}
