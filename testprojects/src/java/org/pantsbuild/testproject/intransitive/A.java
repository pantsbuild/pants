// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.intransitive;

public class A {

  public static void main(String[] args) {
    System.out.println(new A());
    System.out.println(new B());
  }

  @Override public String toString() {
    return "A is for Automata.";
  }

}