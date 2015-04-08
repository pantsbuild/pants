// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.publish.hello.welcome

import org.pantsbuild.testproject.publish.hello.greet.Greeting

// Welcome a collection of things.
//   Given a seq of strings, return a seq of greetings for each of them
//   Handy wrapper around the greet Java library.

object WelcomeEverybody {
  def apply(everybody: Seq[String]): Seq[String] = {
    everybody.map(x => Greeting.greet(x))
  }
}
