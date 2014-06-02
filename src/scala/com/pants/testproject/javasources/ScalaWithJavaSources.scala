// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.testproject.javasources

class ScalaWithJavaSources {
  def example(): String = {
    new JavaSource().doStuff()
  }
}
