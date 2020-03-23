package opts;

import java.lang.management.ManagementFactory;
import java.lang.management.RuntimeMXBean;
import java.util.List;

public class Main {
    private static void printProperty(String name) {
        String value = System.getProperty(name);
        System.out.println("Property " + name + " is " + value);
    }

    private static void printFlag(String name) {
        RuntimeMXBean runtimeMxBean = ManagementFactory.getRuntimeMXBean();
        List<String> arguments = runtimeMxBean.getInputArguments();
        if (arguments.contains(name)) {
          System.out.println("Flag " + name + " is set");
        } else {
          System.out.println("Flag " + name + " is NOT set");
        }
    }

    private static void printMaxHeapSize() {
      System.out.println("Max Heap Size: " + Runtime.getRuntime().maxMemory());
    }

    public static void main(String args[]) {
       printProperty("property.color");
       printProperty("property.size");
       printFlag("-DMyFlag");
       printMaxHeapSize();
    }
}
