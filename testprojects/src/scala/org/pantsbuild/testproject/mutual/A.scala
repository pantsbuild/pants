package org.pantsbuild.testproject.mutual

class A {
  def b: B = {
    val b = new B
    b.a.b
  }
}

object A extends App {
  println("A")
}