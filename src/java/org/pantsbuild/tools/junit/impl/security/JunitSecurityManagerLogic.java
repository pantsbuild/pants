package org.pantsbuild.tools.junit.impl.security;

import java.io.File;
import java.io.IOException;
import java.util.HashSet;
import java.util.Set;
import java.util.logging.Logger;

class JunitSecurityManagerLogic {
    private static Logger logger = Logger.getLogger("pants-junit-sec-mgr-logic");

    private static final Set<String> localhostNames = new HashSet<>();

    static {
      JunitSecurityManagerLogic.localhostNames.add("localhost");
      JunitSecurityManagerLogic.localhostNames.add("127.0.0.1");
    }

    private final JunitSecurityManagerConfig config;
    private final JunitSecurityContextLookupAndErrorCollection contextLookupAndErrorCollection;

    public JunitSecurityManagerLogic(JunitSecurityManagerConfig config, JunitSecurityContextLookupAndErrorCollection contextLookupAndErrorCollection) {
      this.config = config;
      this.contextLookupAndErrorCollection = contextLookupAndErrorCollection;
    }

  boolean disallowsThreadsFor(TestSecurityContext context) {
    switch (config.getThreadHandling()) {
      case allowAll:
        return false;
      case disallow:
        return true;
      case disallowLeakingTestCaseThreads:
        return true;
      case disallowLeakingTestSuiteThreads:
        return context.isSuite();
      default:
        return false;
    }
  }

  boolean disallowsFileAccess(TestSecurityContext testSecurityContext, String filename) {
      JunitSecurityManagerConfig.FileHandling fileHandling = config.getFileHandling();
      if (fileHandling == JunitSecurityManagerConfig.FileHandling.allowAll) {
        return false;
      }
      // NB: This escape hatch allows lazy loading of things like the locale jar, which is pulled from
      //     the jre location.
      if (filename.startsWith(System.getProperty("java.home"))) {
        log("disallowsFileAccess", "is a framework call");
        return false;
      }

      if (isFrameworkContext(testSecurityContext)) {
        // calls within the framework should be passed through.
        log("disallowsFileAccess", "is a framework call");
        return false;
      } else if (isRedirectedOutputFile(testSecurityContext, filename)) {
        log("disallowsFileAccess", "is a framework call to the redirected output");
        return false;
      } else {
        if (fileHandling == JunitSecurityManagerConfig.FileHandling.onlyCWD) {
          String workingDir = System.getProperty("user.dir");
          try {
            String canonicalPath = new File(filename).getCanonicalPath();
            return !canonicalPath.startsWith(workingDir);
          } catch (IOException e) {
            // TODO Do something better here
            e.printStackTrace();
          }
        }
        return fileHandling == JunitSecurityManagerConfig.FileHandling.disallow;
      }
    }

    public boolean disallowSystemExit() {
      return contextLookupAndErrorCollection.disallowSystemExit();
    }

    boolean disallowConnectionTo(String host, int port) {
      switch (config.getNetworkHandling()) {
        case allowAll:
          return false;
        case onlyLocalhost:
          return !hostIsLocalHost(host);
        case disallow:
          return true;
      }

      return config.getNetworkHandling() != JunitSecurityManagerConfig.NetworkHandling.allowAll;
    }

    private boolean hostIsLocalHost(String host) {
      return localhostNames.contains(host);
    }

    private boolean isRedirectedOutputFile(TestSecurityContext testSecurityContext, String filename) {
      // TODO make this a bit more bulletproof
      return filename.endsWith(".out.txt") || filename.endsWith(".err.txt");
    }

    private boolean isFrameworkContext(TestSecurityContext testSecurityContext) {
      return testSecurityContext == null; // TODO introduce null object for framework contexts
    }

    private static void log(String methodName, String msg) {
      logger.fine("---" + methodName + ":" + msg);
    }

  public boolean perClassThreadHandling() {
    return config.getThreadHandling() ==
        JunitSecurityManagerConfig.ThreadHandling.disallowLeakingTestSuiteThreads;
  }
}
