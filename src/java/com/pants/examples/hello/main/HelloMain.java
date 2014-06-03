// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.hello.main;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.InputStream;
import java.util.Scanner;

import com.pants.examples.hello.greet.Greeting;

public class HelloMain {

  public static void main(String[] args) throws FileNotFoundException {
    // Target of greeting is config'd in greetee.txt file, so read that:
    String greetee = "default world";
    Scanner scanner = null;
    try {
	scanner = new Scanner(new File("greetee.txt")).useDelimiter("\\Z");
	greetee = scanner.next();
    } finally {
	if (scanner != null) {
	    scanner.close();
	}
    }

    System.out.println(Greeting.greet(greetee));

    // Target of other greeting is config'd in resource, so read that:
    greetee = "default world";
    try {
	InputStream is = HelloMain.class.getClassLoader()
	    .getResourceAsStream("com/pants/example/hello/world.txt");
	scanner = new Scanner(is).useDelimiter("\\Z");
	greetee = scanner.next();
    } finally {
	if (scanner != null) {
	    scanner.close();
	}
    }

    System.out.println(Greeting.greet(greetee));
  }
  private HelloMain() {
    // not called. placates checkstyle
  }
}
