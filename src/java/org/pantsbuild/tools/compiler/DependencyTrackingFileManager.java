// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.compiler;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map.Entry;
import java.util.Set;

import javax.tools.FileObject;
import javax.tools.ForwardingJavaFileManager;
import javax.tools.JavaFileObject;
import javax.tools.JavaFileObject.Kind;
import javax.tools.StandardJavaFileManager;
import javax.tools.StandardLocation;

/**
 * A file manager that intercepts requests for class output files to track dependencies.
 *
 * Stores dependencies from source file to class file in a line oriented plain text format where
 * each line has the following format:
 * <pre>
 * [source file path] -&gt; [class file path]
 * </pre>
 *
 * There may be multiple lines per source file if the file contains multiple top level classes or
 * inner classes.  All paths are normalized to be relative to the classfile output directory.
 */
final class DependencyTrackingFileManager
    extends ForwardingJavaFileManager<StandardJavaFileManager> {

  private final LinkedHashMap<String, List<String>> sourceToClasses =
      new LinkedHashMap<String, List<String>>();
  private final Set<String> priorSources = new HashSet<String>();
  private final File dependencyFile;

  private List<String> outputPath;
  private File outputDir;

  DependencyTrackingFileManager(StandardJavaFileManager fileManager, File dependencies)
      throws IOException {

    super(fileManager);
    this.dependencyFile = dependencies;

    if (dependencyFile.exists()) {
      System.out.println("Reading existing dependency file at " + dependencies);
      BufferedReader dependencyReader = new BufferedReader(new FileReader(dependencies));
      try {
        int line = 0;
        while (true) {
          String mapping = dependencyReader.readLine();
          if (mapping == null) {
            break;
          }

          line++;
          String[] components = mapping.split(" -> ");
          if (components.length != 2) {
            System.err.printf("Ignoring malformed dependency in %s[%d]: %s\n",
                dependencies, line, mapping);
          } else {
            String sourceRelpath = components[0];
            String classRelpath = components[1];
            addMapping(sourceRelpath, classRelpath);
          }
        }
      } finally {
        dependencyReader.close();
      }
    }
    priorSources.addAll(sourceToClasses.keySet());
  }

  @Override
  public JavaFileObject getJavaFileForOutput(Location location, String className, Kind kind,
      FileObject sibling) throws IOException {

    JavaFileObject file = super.getJavaFileForOutput(location, className, kind, sibling);
    // We only map loose source files to class file output.
    if (Kind.CLASS == kind && sibling != null && sibling.toUri().getPath() != null) {
      addMapping(toOutputRelpath(sibling), toOutputRelpath(file));
    }
    return file;
  }

  private void addMapping(String sourceFile, String classFile) {
    List<String> classFiles = sourceToClasses.get(sourceFile);
    if (classFiles == null || priorSources.remove(sourceFile)) {
      classFiles = new ArrayList<String>();
      sourceToClasses.put(sourceFile, classFiles);
    }
    classFiles.add(classFile);
  }

  private String toOutputRelpath(FileObject file) {
    List<String> base = new ArrayList<String>(getOutputPath());
    List<String> path = toList(file);
    for (Iterator<String> baseIter = base.iterator(), pathIter = path.iterator();
         baseIter.hasNext() && pathIter.hasNext();) {
      if (!baseIter.next().equals(pathIter.next())) {
        break;
      } else {
        baseIter.remove();
        pathIter.remove();
      }
    }

    if (!base.isEmpty()) {
      path.addAll(0, Collections.nCopies(base.size(), ".."));
    }
    return join(path);
  }

  private String join(List<String> components) {
    StringBuilder path = new StringBuilder();
    for (int i = 0, max = components.size(); i < max; i++) {
      if (i > 0) {
        path.append(File.separatorChar);
      }
      path.append(components.get(i));
    }
    return path.toString();
  }

  private List<String> toList(FileObject path) {
    return new ArrayList<String>(Arrays.asList(path.toUri().normalize().getPath().split("/")));
  }

  private synchronized List<String> getOutputPath() {
    if (outputPath == null) {
      List<String> components = new ArrayList<String>();
      File f = getOutputDir();
      while (f != null) {
        components.add(f.getName());
        f = f.getParentFile();
      }
      Collections.reverse(components);
      outputPath = components;
    }
    return outputPath;
  }

  private synchronized File getOutputDir() {
    if (outputDir == null) {
      Iterable<? extends File> location = fileManager.getLocation(StandardLocation.CLASS_OUTPUT);
      if (location == null || !location.iterator().hasNext()) {
        throw new IllegalStateException("Expected to be called after compilation started - found "
            + "no class output dir.");
      }
      for (File path : location) {
        if (outputDir != null) {
          throw new IllegalStateException("Expected exactly 1 output path");
        }
        outputDir = path;
      }
    }
    return outputDir;
  }

  @Override
  public void close() throws IOException {
    super.close();

    System.out.println("Writing class dependency file to " + dependencyFile);
    PrintWriter dependencyWriter = new PrintWriter(new FileWriter(dependencyFile, false));
    try {
      for (Entry<String, List<String>> entry : sourceToClasses.entrySet()) {
        String sourceFile = entry.getKey();
        for (String classFile : entry.getValue()) {
          if (!priorSources.contains(sourceFile) || doesMappingExist(sourceFile, classFile)) {
            dependencyWriter.printf("%s -> %s\n", sourceFile, classFile);
          }
        }
      }
    } finally {
      dependencyWriter.close();
    }
  }

  private boolean doesMappingExist(String sourceFile, String classFile) {
    return new File(getOutputDir(), sourceFile).exists()
        && new File(getOutputDir(), classFile).exists();
  }
}
