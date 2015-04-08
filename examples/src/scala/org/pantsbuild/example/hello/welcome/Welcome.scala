// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.hello.welcome

import org.pantsbuild.example.hello.greet.Greeting

// Welcome a collection of things.
//   Given a seq of strings, return a seq of greetings for each of them
//   Handy wrapper around the greet Java library.

object WelcomeEverybody {
  def apply(everybody: Seq[String]): Seq[String] = {
    everybody.map(x => Greeting.greet(x))
  }
}
