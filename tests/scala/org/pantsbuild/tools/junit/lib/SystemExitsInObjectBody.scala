package org.pantsbuild.tools.junit.lib

import org.scalatest.FreeSpec

object SystemExitsInObjectBody extends FreeSpec {
  System.exit(2)

  var something: Int = 1
}

class SystemExitsInObjectBody extends FreeSpec {
  private val aUsage = SystemExitsInObjectBody.something
  "test" - {
    "passing" in {

    }
  }
}
