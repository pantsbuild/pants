// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.hello.welcome

import org.junit.runner.RunWith
import org.specs._

@RunWith(classOf[runner.JUnitSuiteRunner])
class WelSpec extends Specification with runner.JUnit {
  "Welcome" should {
    "greet nobody" in {
      WelcomeEverybody(List()).size mustEqual 0
    }
    "greet both" in {
      WelcomeEverybody(List("Pat", "Sandy")).size mustEqual 2
    }
  }
}
