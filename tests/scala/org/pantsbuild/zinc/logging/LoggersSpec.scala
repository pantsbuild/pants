// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.zinc.logging

import java.io.{ File, PrintWriter, StringWriter }

import com.google.common.base.Charsets
import com.google.common.io.Files

import sbt.{ ConsoleOut, Level }

import org.junit.runner.RunWith
import org.scalatest.WordSpec
import org.scalatest.junit.JUnitRunner
import org.scalatest.matchers.MustMatchers

@RunWith(classOf[JUnitRunner])
class LoggersSpec extends WordSpec with MustMatchers {
  "Loggers" should {
    "be compound" in {
      // create a compound logger
      val stdout = new StringWriter()
      val captureFile = File.createTempFile("loggers", "spec")
      val log =
        Loggers.create(
          Level.Debug,
          false,
          Seq(),
          ConsoleOut.printWriterOut(new PrintWriter(stdout)),
          Some(captureFile)
        )

      // log something, and confirm it's captured in both locations
      val msg = "this is a log message!"
      log.debug(msg)
      stdout.toString must include(msg)
      Files.toString(captureFile, Charsets.UTF_8) must include(msg)
    }
  }
}
