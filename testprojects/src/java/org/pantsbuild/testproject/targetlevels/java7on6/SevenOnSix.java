// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.targetlevels.java7on6;

import org.pantsbuild.testproject.targetlevels.java6.Six;

/**
 * Java 1.7 class depending on a Java 1.6 class.
 */
public class SevenOnSix<T> {
    public static void main(String[] args) {
        System.out.println("SevenOnSix should have been compiled for java 1.7.");
        Six.main(args);
        SevenOnSix<String> sevenOnSix = new SevenOnSix<>(); // Shouldn't compile in java 6.
    }
}
