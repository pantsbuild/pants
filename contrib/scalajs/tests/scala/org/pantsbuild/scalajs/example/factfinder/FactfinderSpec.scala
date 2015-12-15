// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.scalajs.example.factfinder

import org.junit.runner.RunWith
import org.scalatest.MustMatchers
import org.scalatest.WordSpec
import org.scalatest.junit.JUnitRunner

import com.google.common.base.Charsets
import com.google.common.io.Resources

@RunWith(classOf[JUnitRunner])
class FactfinderSpec extends WordSpec with MustMatchers {
  "Factfinder" should {
    "be available on the classpath" in {
      val factfinderURL = Resources.getResource("factfinder.js")
      factfinderURL must not equal(null)
      Resources.toString(factfinderURL, Charsets.UTF_8).nonEmpty must equal(true)
    }
  }
}
