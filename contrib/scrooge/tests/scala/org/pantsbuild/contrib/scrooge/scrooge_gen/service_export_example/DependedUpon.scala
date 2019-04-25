package org.pantsbuild.contrib.scrooge.scrooge_gen.service_export_example

import org.pantsbuild.contrib.scrooge.scrooge_gen.service_export_example.SayThis

object SayThatPlusThis {
  def apply(that: String, this: String): String = {
    "Say that:" + that + "; " + SayThis(this)
  }
}