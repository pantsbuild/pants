// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.testproject.javasources;

public class JavaSource {

  public String doStuff() {
    ScalaWithJavaSources circularDependencyHell = new ScalaWithJavaSources();
    return "do it";
  }

}
