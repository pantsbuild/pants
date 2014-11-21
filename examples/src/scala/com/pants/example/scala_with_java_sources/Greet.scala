// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.scala_with_java_sources;

import com.pants.examples.java_sources.Greet


object GreetEverybody {

  def greetAll(everybody: Array[String]): Array[String] = {
    everybody.map(x => Greet.greet(x))
  }
}
