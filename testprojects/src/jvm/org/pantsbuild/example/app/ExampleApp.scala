package org.pantsbuild.example.app;

import org.pantsbuild.example.lib.ExampleLib

object ExampleApp {
  def main(args: Array[String]): Unit = {
    println(ExampleLib.hello())
  }
}
