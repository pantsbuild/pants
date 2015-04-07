// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.javasources

import org.pantsbuild.testproject.publish.hello.greet.Greeting

class ScalaWithJavaSources {
  def example(): String = {
    Greeting.greet("Scala Caller with no circular dependency")
    new JavaSource().doStuff()
  }
}
