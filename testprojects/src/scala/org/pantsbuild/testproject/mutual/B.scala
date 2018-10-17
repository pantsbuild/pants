package org.pantsbuild.testproject.mutual

class B {
  def a: A = {
    val a = new A
    a.b.a
  }
}
