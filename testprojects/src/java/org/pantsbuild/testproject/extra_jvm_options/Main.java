package opts;

import java.lang.management.ManagementFactory;
import java.lang.management.RuntimeMXBean;
import java.util.List;

public class Main {
    final static long oneHundredMegabytes = 1024 * 1024 * 100;

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
      Long maxMemory = Runtime.getRuntime().maxMemory();
      if (maxMemory > oneHundredMegabytes) {
        System.out.println("Max Heap Size is more than 100MB");
      } else {
        System.out.println("Max Heap Size: " + maxMemory);
      }
    }

    public static void main(String args[]) {
       printProperty("property.color");
       printProperty("property.size");
       printFlag("-DMyFlag");
       printMaxHeapSize();
    }
}
