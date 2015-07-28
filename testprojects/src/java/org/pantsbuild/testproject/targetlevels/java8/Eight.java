// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.targetlevels.java8;

public class Eight {
    public static void main(String[] args) {
        Runnable printMessage = () -> System.out.println("Compiled to java 1.8.");
        printMessage.run();
    }
}
