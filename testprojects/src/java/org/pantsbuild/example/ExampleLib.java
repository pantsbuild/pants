package org.pantsbuild.example;

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

    public static void main(String[] args) {
        System.out.println(new ExampleLib().getGreeting());
    }
}


// TODO: Replicate in public class, and then in a public class in another package.
class SerializedThing {
    
    public String contents;

}
