package org.pantsbuild.tools.junit.impl.security;

import java.io.File;
import java.io.IOException;
import java.util.HashSet;
import java.util.Set;
import java.util.logging.Logger;

import static org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig.FileHandling;
import static org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig.NetworkHandling;
import static org.pantsbuild.tools.junit.impl.security.JunitSecurityManagerConfig.ThreadHandling;

class JunitSecurityManagerLogic {
  private static Logger logger = Logger.getLogger("pants-junit-sec-mgr-logic");

  private static final Set<String> localhostNames = new HashSet<>();

  static {
    JunitSecurityManagerLogic.localhostNames.add("localhost");
    JunitSecurityManagerLogic.localhostNames.add("127.0.0.1");
  }

  private final JunitSecurityManagerConfig config;
  private final JunitSecurityContextLookupAndErrorCollection contextLookupAndErrorCollection;

  public JunitSecurityManagerLogic(JunitSecurityManagerConfig config,
                                   JunitSecurityContextLookupAndErrorCollection contextLookupAndErrorCollection) {
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
    FileHandling fileHandling = config.getFileHandling();
    switch (fileHandling) {
      case allowAll:
        return false;
      case onlyCWD:
      case disallow:
        if (isFrameworkContext(testSecurityContext)) {
          // calls within the framework should be passed through.
          log("disallowsFileAccess", "is a framework call");
          return false;
        }
        String canonicalFile;
        try {
          canonicalFile = new File(filename).getCanonicalPath();
        } catch (IOException e) {
          // TODO maybe should be something else?
          return false;
        }

        if (canonicalFile.startsWith(System.getProperty("java.home"))) {
          // NB: This escape hatch allows lazy loading of things like the locale jar, which is
          // pulled from the jre location.
          log("disallowsFileAccess", "is calling into the jdk");
          return false;
        }
        if (isRedirectedOutputFile(testSecurityContext, filename)) {
          log("disallowsFileAccess", "is a framework call to the redirected output");
          return false;
        }
        if (fileHandling == FileHandling.onlyCWD &&
            canonicalFile.startsWith(System.getProperty("user.dir"))) {
          log("disallowsFileAccess", "in CWD");
          return false;
        }
        return true;
      default:
        return false;
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

    return config.getNetworkHandling() != NetworkHandling.allowAll;
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
        ThreadHandling.disallowLeakingTestSuiteThreads;
  }
}
