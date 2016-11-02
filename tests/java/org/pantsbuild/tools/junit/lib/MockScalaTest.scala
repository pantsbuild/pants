package org.pantsbuild.tools.junit.lib

import org.scalatest.FreeSpec

/**
  * Created by dbrewster on 11/2/16.
  */
class MockScalaTest extends FreeSpec {
  "test" - {
    "should pass" in {
      TestRegistry.registerTestCall("MockScalaTest-1")
    }
  }
}
