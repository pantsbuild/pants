// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example

// A simple jvm binary to test the jvm_run task on. Try, e.g.,
// ./pants -ldebug run --run-jvm-jvm-options='-Dfoo=bar' --run-jvm-args="Foo Bar" \\
//   examples/src/scala/org/pantsbuild/example:jvm-run-example


object JvmRunExample {
  def main(args: Array[String]) {
    println("Hello, World")
    println("args: " + args.mkString(", "))
  }
}
