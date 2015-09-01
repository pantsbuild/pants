package org.pantsbuild.example.factfinder

import scala.scalajs.js.annotation.JSExport
import scala.scalajs.js.JSApp

import org.pantsbuild.example.fact.Factorial

object Main extends JSApp {
  def main(): Unit = println(s"Hello from ScalaJS! ${Factorial(10)}")
}
