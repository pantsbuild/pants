// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.autovalue;

import com.google.auto.value.AutoValue;

public class AutoValueMain {

  @AutoValue
  abstract static class ValueType {
    abstract String message();

    static ValueType create(String message) {
      return new AutoValue_AutoValueMain_ValueType(message);
    }
  }

  public static void main(String[] args) {
    ValueType valueType = ValueType.create("Hello Autovalue!");
    System.out.println(valueType.message());
  }
}
