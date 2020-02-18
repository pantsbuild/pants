package org.pantsbuild.example.several_scala_targets.greet_json_names

import java.io.{BufferedReader, InputStreamReader}

object GreetingJsonNames {
  def getJSONResource: String = {
    val is =
      this.getClass.getClassLoader.getResourceAsStream(
        "names_to_greet/names.json"
      )
    try {
      new BufferedReader(new InputStreamReader(is)).readLine()
    } finally {
      is.close()
    }
  }
  def main(args: Array[String]) {
    println("Hello, " + getJSONResource + "!")
  }
}
