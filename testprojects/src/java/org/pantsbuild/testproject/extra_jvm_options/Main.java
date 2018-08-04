package opts;

public class Main {
    private static void printProperty(String name) {
        String value = System.getProperty(name);
        System.out.println("Property " + name + " is " + value);
    }

    public static void main(String args[]) {
       printProperty("property.color");
       printProperty("property.size");
    }
}