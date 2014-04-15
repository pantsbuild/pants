// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.example.hello.exe

import com.pants.example.hello.welcome

// A simple jvm binary to illustrate Scala BUILD targets

object Exe {
  def main(args: Array[String]) {
    println("Num args passed: " + args.size + ". Stand by for welcome...")
    if (args.size <= 0) {
      println("Hello, World!")
    } else {
      val w = welcome.WelcomeEverybody(args)
      w.foreach(s => println(s))
    }
  }
}
