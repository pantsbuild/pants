package org.pantsbuild.scalajs.example.factfinder

import scala.scalajs.js.annotation.JSExport
import scala.scalajs.js.JSApp

import org.pantsbuild.example.fact.Factorial

@JSExport
object Factfinder extends JSApp {
  def main(): Unit = println(s"Hello from ScalaJS! ${Factorial(10)}")

  /** NB: exported as Int for ease of use. */
  @JSExport
  def fact(i: Int): String = Factorial(i).toString
}
