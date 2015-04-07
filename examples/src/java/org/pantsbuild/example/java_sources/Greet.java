// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.java_sources;

public class Greet {
    public static String greet(String message){
        if (message.isEmpty() || message ==null) {
            return "Helo world!";
        }
        return "Hello " + message;
    }
}