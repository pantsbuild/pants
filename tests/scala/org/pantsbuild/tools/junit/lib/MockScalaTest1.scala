package org.pantsbuild.tools.junit.lib

import org.scalatest.FreeSpec

class MockScalaTest1 extends FreeSpec {
  "test" - {
    "should pass" in {
      TestRegistry.registerTestCall("MockScalaTest-2")
    }
  }
}
