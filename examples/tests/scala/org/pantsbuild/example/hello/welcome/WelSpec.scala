// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.hello.welcome

import org.junit.runner.RunWith
import org.scalatest.WordSpec
import org.scalatest.junit.JUnitRunner
import org.scalatest.MustMatchers

@RunWith(classOf[JUnitRunner])
class WelSpec extends WordSpec with MustMatchers {
  "Welcome" should {
    "greet nobody" in {
      WelcomeEverybody(List()).size mustEqual 0
    }
    "greet both" in {
      WelcomeEverybody(List("Pat", "Sandy")).size mustEqual 2
    }
  }
}
