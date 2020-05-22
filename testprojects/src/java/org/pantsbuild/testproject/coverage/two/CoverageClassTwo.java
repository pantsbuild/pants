// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.coverage.two;

/**
 * This is a trivial class for use in testing pants java code coverage
 * functionality. It is initialized with a given value, and has methods
 * to return the value, mult/div some other value.
 */
public class CoverageClassTwo {
    private final int magnitude;

    public CoverageClassTwo(int magnitude) {
        this.magnitude = magnitude;
    }

    public int mult(int toMult) {
        return this.magnitude * toMult;
    }

    public int div(int toDiv) {
        return this.magnitude / toDiv;
    }

    public int multIfTrue(boolean isTrue, int toMult) {
        if (isTrue) {
            return mult(toMult);
        }
        return this.magnitude;
    }
}