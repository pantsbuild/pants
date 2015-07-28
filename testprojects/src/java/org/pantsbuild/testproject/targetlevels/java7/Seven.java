// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.targetlevels.java7;

public class Seven<T> {
    public static void main(String[] args) {
        System.out.println("Seven should have been compiled for java 1.7.");
        Seven<String> seven = new Seven<>();
    }
}
