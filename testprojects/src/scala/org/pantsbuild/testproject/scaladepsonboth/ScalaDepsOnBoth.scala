// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.scaladepsonboth

import org.pantsbuild.testproject.javasources.ScalaWithJavaSources

class ScalaDepsOnBoth {
  def example(): String = {
    System.out.println("ScalaDepsOnBoth calling ScalaWithJavaSources().example()")
    new ScalaWithJavaSources().example()
  }
}
