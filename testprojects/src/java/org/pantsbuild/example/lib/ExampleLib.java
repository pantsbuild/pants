package org.pantsbuild.example.lib;

import com.fasterxml.jackson.databind.ObjectMapper;

public class ExampleLib {

    private String template = "{\"contents\": \"Hello, World!\"}";

    public String getGreeting() {
        ObjectMapper mapper = new ObjectMapper();
        try {
            SerializedThing thing = mapper.readValue(template, SerializedThing.class);
            return thing.contents;
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    public static String hello() {
        return new ExampleLib().getGreeting();
    }
}

class SerializedThing {
    public String contents;
}
