package org.pantsbuild.example.lib;

import com.fasterxml.jackson.databind.ObjectMapper;

public class ExampleLib { 
    public static String hello() {
        ObjectMapper o = new ObjectMapper();
        return "Hello, World and frederick";
    }
}
