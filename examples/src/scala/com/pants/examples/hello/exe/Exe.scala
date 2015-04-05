// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.hello.exe

import java.io.{BufferedReader, InputStreamReader}

import com.pants.examples.hello.welcome

// A simple jvm binary to illustrate Scala BUILD targets

object Exe {
  /** Test that resources are properly namespaced. */
  def getWorld: String = {
    val is =
      this.getClass.getClassLoader.getResourceAsStream(
        "com/pants/examples/hello/world.txt"
      )
    try {
      new BufferedReader(new InputStreamReader(is)).readLine()
    } finally {
      is.close()
    }
  }

  def main(args: Array[String]) {
    println("Num args passed: " + args.size + ". Stand by for welcome...")
    if (args.size <= 0) {
      println("Hello, " + getWorld + "!")
    } else {
      val w = welcome.WelcomeEverybody(args)
      w.foreach(s => println(s))
    }
  }
}
