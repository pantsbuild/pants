// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.testproject.publish

// A simple jvm binary to test the jvm_run task on. Try, e.g.,
// ./pants run src/scala/com/pants/example:jvm-run-example \\
//   -ldebug --jvm-run-jvm-options=-Dfoo=bar --jvm-run-args="Foo Bar"

object JvmRunExample {
  def main(args: Array[String]) {
    println("Hello, World")
    println("args: " + args.mkString(", "))
  }
}
