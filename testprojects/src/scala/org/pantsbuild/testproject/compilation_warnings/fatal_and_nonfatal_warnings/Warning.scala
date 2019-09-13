package org.pantsbuild.testproject.compilation_warnings

object Warning {
  // inexhaustive match warning
  def f(x: Boolean) = x match { case true => }
}
