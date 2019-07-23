// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.rsc_compat

object RscCompatFixed {

  def x0: Int = 42

  def x1: String = "42"

  class MyClass

  val x2: MyClass = new MyClass
}
