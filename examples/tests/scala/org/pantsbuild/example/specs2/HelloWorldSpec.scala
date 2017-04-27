// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.specs2

import org.specs2.mutable.SpecificationWithJUnit

class HelloWorldSpec extends SpecificationWithJUnit {

  "add three numbers" in {
    1 + 1 + 1 mustEqual 3
  }

  "add 2 numbers" in {
    1 + 1 mustEqual 2
  }
}