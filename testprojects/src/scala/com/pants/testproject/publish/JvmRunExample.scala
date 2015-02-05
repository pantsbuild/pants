// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.testproject.publish

// A simple jvm binary to test the jvm_run task on. Try, e.g.,
// ./pants -ldebug run --run-jvm-jvm-options='-Dfoo=bar' --run-jvm-args="Foo Bar" \\
//   testprojects/src/scala/com/pants/testproject/publish:jvm-run-example-lib

object JvmRunExample {
  def main(args: Array[String]) {
    println("Hello, World")
    println("args: " + args.mkString(", "))
  }
}
