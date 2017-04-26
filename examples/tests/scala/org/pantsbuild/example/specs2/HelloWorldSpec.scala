package org.pantsbuild.example.specs2

import org.junit.runner.RunWith
import org.specs2.mutable.Specification
//import org.specs2.runner.JUnitRunner
import org.scalatest.junit.JUnitRunner

@RunWith(classOf[JUnitRunner])
object HelloWorldSpec extends Specification {

  "add three numbers" in {
    1 + 1 + 1 mustEqual 3
  }

  "add 2 numbers" in {
    1 + 1 mustEqual 2
  }
}