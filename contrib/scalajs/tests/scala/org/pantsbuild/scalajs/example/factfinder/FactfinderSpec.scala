// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.scalajs.example.factfinder

import org.junit.runner.RunWith
import org.scalatest.MustMatchers
import org.scalatest.WordSpec
import org.scalatest.junit.JUnitRunner

import org.mozilla.javascript.Context

import com.google.common.base.Charsets
import com.google.common.io.Resources

@RunWith(classOf[JUnitRunner])
class FactfinderSpec extends WordSpec with MustMatchers {
  "Factfinder" should {
    "be available on the classpath" in {
      factfinderResource must not equal(null)
    }

    "work when run with rhino" in {
			val cx = Context.enter()
			try {
			  val scope = cx.initStandardObjects()
        val factfinder = Resources.toString(factfinderResource, Charsets.UTF_8)
			  val result: Any = cx.evaluateString(scope, factfinder, "<cmd>", 1, null)

			  Context.toString(result) must equal("1")
			} finally {
			  // Exit from the context.
			  Context.exit()
			}
    }
  }

  def factfinderResource =
    Resources.getResource("factfinder.js")
}
