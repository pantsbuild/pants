// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.hello.main;

import org.apache.log4j.Logger;
import org.apache.log4j.PropertyConfigurator;

import com.pants.examples.hello.greet.Greeting;

public class HelloMain {
  static Logger log = Logger.getLogger("hello.main");

  public static void main(String[] args) {
    PropertyConfigurator.configure("log4j.properties");
    log.info(Greeting.greet("world"));
  }
  private HelloMain() {
    // not called. placates checkstyle
  }
}
