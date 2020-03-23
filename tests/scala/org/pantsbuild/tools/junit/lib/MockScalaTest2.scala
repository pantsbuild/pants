package org.pantsbuild.tools.junit.lib

import org.scalatest.FreeSpec

class MockScalaTest2 extends FreeSpec {
  "test" - {
    "should pass" in {
      TestRegistry.registerTestCall("MockScalaTest-3")
    }
  }
}
