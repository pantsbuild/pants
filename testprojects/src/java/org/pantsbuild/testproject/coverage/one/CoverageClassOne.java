// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.coverage.one;

/**
 * This is a trivial class for use in testing pants java code coverage
 * functionality. It is initialized with a given value, and has methods
 * to return the value, +/- some other value.
 */
public class CoverageClassOne {
    private final int magnitude;

    public CoverageClassOne(int magnitude) {
        this.magnitude = magnitude;
    }

    public int add(int toAdd) {
        return this.magnitude + toAdd;
    }

    public int sub(int toSub) {
        return this.magnitude - toSub;
    }

    public int addIfTrue(boolean isTrue, int toAdd) {
        if (isTrue) {
            return add(toAdd);
        }
        return this.magnitude;
    }
}