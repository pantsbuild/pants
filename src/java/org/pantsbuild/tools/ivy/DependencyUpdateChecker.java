// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.ivy;

import java.io.File;
import java.io.IOException;
import java.io.PrintStream;
import java.text.ParseException;
import java.util.ArrayList;
import java.util.List;
import org.apache.ivy.Ivy;
import org.apache.ivy.core.module.descriptor.Configuration;
import org.apache.ivy.core.module.descriptor.DefaultModuleDescriptor;
import org.apache.ivy.core.module.descriptor.DependencyDescriptor;
import org.apache.ivy.core.module.descriptor.ModuleDescriptor;
import org.apache.ivy.core.module.id.ModuleRevisionId;
import org.apache.ivy.core.report.ResolveReport;
import org.apache.ivy.core.resolve.IvyNode;
import org.apache.ivy.core.resolve.ResolveOptions;
import org.apache.ivy.core.settings.IvySettings;
import org.apache.ivy.util.url.URLHandler;
import org.apache.ivy.util.url.URLHandlerDispatcher;
import org.apache.ivy.util.url.URLHandlerRegistry;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.Option;
import org.kohsuke.args4j.ParserProperties;
import org.pantsbuild.args4j.InvalidCmdLineArgumentException;

/**
 * Based on checkdepsupdate ant task
 * http://ant.apache.org/ivy/history/latest-milestone/use/checkdepsupdate.html
 * That displays jar dependency updates on the console
 *
 * TODO: Generate json output for dependency tools
 */
public class DependencyUpdateChecker {
  // See http://ant.apache.org/ivy/history/2.4.0/settings/version-matchers.html for other
  // revision options.
  @Option(name = "-revision-to-check", metaVar = "<revision>", usage = "Target revision to check.")
  private String revisionToCheck = "latest.integration";

  @Option(name = "-check-if-changed", usage = "The resolve will compare the result "
      + "with the last resolution done on this module to define the property ivy.deps.changed. "
      + "Disabling this check may provide slightly better performance.")
  private boolean checkIfChanged = false;

  @Option(name = "-show-transitive", usage = "Show updates on transitive dependencies")
  private boolean showTransitive = false;

  @Option(name = "-settings", metaVar = "<settingsfile>", required = true,
      usage = "Ivy settings file")
  public void setSettingsFile(File settingsFile) throws InvalidCmdLineArgumentException {
    if (!settingsFile.exists()) {
      throw new InvalidCmdLineArgumentException(
          "-settings", settingsFile, "Ivy settings file not found");
    } else if (settingsFile.isDirectory()) {
      throw new InvalidCmdLineArgumentException(
          "-settings", settingsFile, "Ivy settings file is not a file");
    }
    this.settingsFile = settingsFile;
  }
  private File settingsFile;

  @Option(name = "-ivy", metaVar = "<ivyfile>", required = true, usage = "Ivy file")
  public void setIvyFile(File ivyFile) throws InvalidCmdLineArgumentException {
    if (!ivyFile.exists()) {
      throw new InvalidCmdLineArgumentException("-ivy", ivyFile, "Ivy file not found");
    } else if (ivyFile.isDirectory()) {
      throw new InvalidCmdLineArgumentException("-ivy", ivyFile, "Ivy file is not a file");
    }
    this.ivyFile = ivyFile;
  }
  private File ivyFile;

  @Option(name = "-confs", metaVar = "<configurations>", usage = "Resolve given configurations")
  public void setConfs(String c) {
    confs = c.split(",");
    for (int i = 0; i < confs.length; i++) {
      confs[i] = confs[i].trim();
    }
  }

  private String[] confs = { "default" };

  /** Should be set to false for unit testing via {@link #setCallSystemExitOnFinish} */
  private static volatile boolean callSystemExitOnFinish = true;

  private Ivy ivyInstance;

  private static PrintStream logStream = System.out;
  private final String INDENTATION = "  ";

  public void log(String msg) {
    logStream.println(msg);
  }

  public static void setLogStream(PrintStream stream) {
    logStream = stream;
  }

  public void execute() throws IOException, ParseException {
    ResolveReport resolvedReport = getResolvedReport();
    ModuleDescriptor originalModuleDescriptor = resolvedReport.getModuleDescriptor();

    DefaultModuleDescriptor latestModuleDescriptor = new DefaultModuleDescriptor(
        originalModuleDescriptor.getModuleRevisionId(),
        originalModuleDescriptor.getStatus(), originalModuleDescriptor.getPublicationDate());

    for (Configuration configuration : originalModuleDescriptor.getConfigurations()) {
      latestModuleDescriptor.addConfiguration(configuration);
    }

    for (DependencyDescriptor dependencyDescriptor : originalModuleDescriptor.getDependencies()) {
      ModuleRevisionId upToDateMrid = ModuleRevisionId.newInstance(
          dependencyDescriptor.getDependencyRevisionId(), revisionToCheck);
      latestModuleDescriptor.addDependency(dependencyDescriptor.clone(upToDateMrid));
    }

    ResolveOptions resolveOptions = new ResolveOptions();
    resolveOptions.setDownload(false);
    resolveOptions.setConfs(confs);
    resolveOptions.setCheckIfChanged(checkIfChanged);
    resolveOptions.setTransitive(showTransitive);

    ResolveReport latestReport = getIvyInstance().resolve(latestModuleDescriptor, resolveOptions);

    displayDependencyUpdates(resolvedReport, latestReport);
    if (showTransitive) {
      displayNewDependencyOnLatest(resolvedReport, latestReport);
      displayMissingDependencyOnLatest(resolvedReport, latestReport);
    }
  }

  private void displayDependencyUpdates(ResolveReport originalReport, ResolveReport latestReport) {
    log("Dependency updates available:");
    boolean dependencyUpdateDetected = false;
    for (Object ivyNode : latestReport.getDependencies()) {
      IvyNode latest = (IvyNode) ivyNode;
      for (Object ivyNode2 : originalReport.getDependencies()) {
        IvyNode originalDependency = (IvyNode) ivyNode2;
        if (originalDependency.getModuleId().equals(latest.getModuleId())) {
          if (!originalDependency.getResolvedId().getRevision()
              .equals(latest.getResolvedId().getRevision())) {
            // is this dependency a transitive dependency or a direct dependency
            // (unfortunately the .isTranstive() method doesn't have the same meaning)
            boolean isTransitiveDependency =
                latest.getDependencyDescriptor(latest.getRoot()) == null;
            if ((!isTransitiveDependency) || (isTransitiveDependency && showTransitive)) {
              String message = INDENTATION +
                  originalDependency.getResolvedId().getOrganisation() +
                  '#' +
                  originalDependency.getResolvedId().getName() +
                  (isTransitiveDependency ? " (transitive)" : "") +
                  INDENTATION +
                  originalDependency.getResolvedId().getRevision() +
                  " -> " +
                  latest.getResolvedId().getRevision();
              log(message);
              dependencyUpdateDetected = true;
            }
          }
        }
      }
    }
    if (!dependencyUpdateDetected) {
      log(INDENTATION + "All dependencies are up to date");
    }
  }

  private void displayMissingDependencyOnLatest(ResolveReport originalReport,
      ResolveReport latestReport) {
    List<ModuleRevisionId> listOfMissingDependencyOnLatest = new ArrayList<>();
    for (Object ivyNode : originalReport.getDependencies()) {
      IvyNode originalDependency = (IvyNode) ivyNode;
      boolean dependencyFound = false;
      for (Object ivyNode2 : latestReport.getDependencies()) {
        IvyNode latest = (IvyNode) ivyNode2;
        if (originalDependency.getModuleId().equals(latest.getModuleId())) {
          dependencyFound = true;
        }
      }
      if (!dependencyFound) {
        listOfMissingDependencyOnLatest.add(originalDependency.getId());
      }
    }

    if (listOfMissingDependencyOnLatest.size() > 0) {
      log("List of missing dependencies on latest resolve:");
      for (ModuleRevisionId moduleRevisionId : listOfMissingDependencyOnLatest) {
        log(INDENTATION + moduleRevisionId.toString());
      }
    }
  }

  private void displayNewDependencyOnLatest(ResolveReport originalReport,
      ResolveReport latestReport) {
    List<ModuleRevisionId> listOfNewDependencyOnLatest = new ArrayList<>();
    for (Object ivyNode : latestReport.getDependencies()) {
      IvyNode latest = (IvyNode) ivyNode;

      boolean dependencyFound = false;
      for (Object ivyNode2 : originalReport.getDependencies()) {
        IvyNode originalDependency = (IvyNode) ivyNode2;
        if (originalDependency.getModuleId().equals(latest.getModuleId())) {
          dependencyFound = true;
        }
      }
      if (!dependencyFound) {
        listOfNewDependencyOnLatest.add(latest.getId());
      }
    }
    if (listOfNewDependencyOnLatest.size() > 0) {
      log("List of new dependencies on latest resolve:");
      for (ModuleRevisionId moduleRevisionId : listOfNewDependencyOnLatest) {
        log(INDENTATION + moduleRevisionId.toString());
      }
    }
  }

  public Ivy getIvyInstance() throws ParseException, IOException {
    if (ivyInstance != null) {
      return ivyInstance;
    }

    ivyInstance = Ivy.newInstance();

    URLHandlerDispatcher dispatcher = new URLHandlerDispatcher();
    URLHandler httpHandler = URLHandlerRegistry.getHttp();
    dispatcher.setDownloader("http", httpHandler);
    dispatcher.setDownloader("https", httpHandler);
    URLHandlerRegistry.setDefault(dispatcher);

    IvySettings settings = ivyInstance.getSettings();
    settings.addAllVariables(System.getProperties());

    ivyInstance.configure(settingsFile);

    return ivyInstance;
  }

  public ResolveReport getResolvedReport() throws ParseException, IOException {
    ResolveOptions resolveOptions = new ResolveOptions()
        .setDownload(false)
        .setTransitive(showTransitive)
        .setConfs(confs);

    ResolveReport resolvedReport =
        getIvyInstance().resolve(ivyFile.toURI().toURL(), resolveOptions);
    if (resolvedReport.hasError()) {
      System.err.println("Resolved report has an error");
      exit(1);
    }

    return resolvedReport;
  }

  private static void exit(int code) {
    if (callSystemExitOnFinish) {
      // We're a main - its fine to exit.
      System.exit(code);
    } else {
      if (code != 0) {
        throw new RuntimeException("DependencyUpdateChecker exited with status " + code);
      }
    }
  }

  public static void main(String[] args) throws Exception {
    DependencyUpdateChecker dependencyUpdateChecker = new DependencyUpdateChecker();

    ParserProperties parserProperties = ParserProperties.defaults().withUsageWidth(120);
    CmdLineParser parser = new CmdLineParser(dependencyUpdateChecker, parserProperties);
    try {
      parser.parseArgument(args);
    } catch (InvalidCmdLineArgumentException e) {
      System.err.println(e.getMessage());
      parser.printUsage(System.err);
      System.err.println();
      return;
    }

    dependencyUpdateChecker.execute();
  }

  // ---------------------------- For testing only ---------------------------------

  public static void setCallSystemExitOnFinish(boolean exitOnFinish) {
    callSystemExitOnFinish = exitOnFinish;
  }
}
