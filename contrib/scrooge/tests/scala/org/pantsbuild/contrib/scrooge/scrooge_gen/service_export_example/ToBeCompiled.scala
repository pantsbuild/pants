package org.pantsbuild.contrib.scrooge.scrooge_gen.service_export_example

import org.pantsbuild.contrib.scrooge.scrooge_gen.service_export_example.SayThatPlusThis

object SayThatPlusThisPlusAnother {
  def apply(that: String, this: String, another: String): String = {
    SayThatPlusThis(that, this) + "; Another: " + another
  }
}