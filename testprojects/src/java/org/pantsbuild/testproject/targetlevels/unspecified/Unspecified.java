// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.targetlevels.unspecified;

public class Unspecified {
    public static void main(String[] args) {
        System.out.println("Ostensibly can be compiled at any level, except :six depends on it.");
    }
}
