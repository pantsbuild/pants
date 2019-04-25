package org.pantsbuild.contrib.scrooge.scrooge_gen.service_export_example

import org.pantsbuild.example.scala_with_java_sources.GreetEverybody

class SaySomething {
  def speak(something: String): String = {
    GreetEverybody.greetAll(Seq(something)).mkString(" ")
  }
}
