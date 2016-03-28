// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.intransitive;

public class B {

  public static void main(String[] args) {
    System.out.println(new B());
    try {
      System.out.println(new C());
    } catch (NoClassDefFoundError e) {
      System.out.println("I don't know what C is for.");
    }
  }

  @Override public String toString() { return "B is for Binary."; }

}