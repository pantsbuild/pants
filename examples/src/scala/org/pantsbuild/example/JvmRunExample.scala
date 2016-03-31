// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example

import org.pantsbuild.example.hello.welcome.WelcomeEverybody

// A simple jvm binary to test the jvm_run task on. Try, e.g.,
// ./pants -ldebug run --jvm-run-jvm-options='-Dfoo=bar' --jvm-run-jvm-program-args="Foo Bar" \\
//   examples/src/scala/org/pantsbuild/example:jvm-run-example


object JvmRunExample {
  def main(args: Array[String]) {
    println("Hello, World")
    println(WelcomeEverybody(args).mkString(", "))
  }
}
