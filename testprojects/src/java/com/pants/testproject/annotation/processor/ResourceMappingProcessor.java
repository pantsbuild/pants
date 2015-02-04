// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.testproject.annotation.processor;

import com.google.common.collect.ImmutableSet;
import com.google.common.io.Closer;
import java.io.Closeable;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.io.Writer;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;
import javax.annotation.processing.AbstractProcessor;
import javax.annotation.processing.ProcessingEnvironment;
import javax.annotation.processing.RoundEnvironment;
import javax.lang.model.SourceVersion;
import javax.lang.model.element.Element;
import javax.lang.model.element.TypeElement;
import javax.lang.model.util.ElementFilter;
import javax.lang.model.util.Elements;
import javax.tools.Diagnostic;
import javax.tools.FileObject;
import javax.tools.StandardLocation;

/**
 * A sample implementation of an annotation processor which creates a file named
 * <code>deprecation_report.txt</code>, and creates a META-INF/compiler/resource-mappings/ file.
 * The resource-mappings file is the point of this; pants processes these files
 * to find resources created by annotation processors and add them to the build cache
 */
public class ResourceMappingProcessor extends AbstractProcessor {
  private static final String REPORT_FILE_NAME = "deprecation_report.txt";

  private ProcessingEnvironment processingEnvironment = null;
  private Elements elementUtils;

  private static final class Resource {
    private final FileObject resource;
    private final Writer writer;

    Resource(FileObject resource, Writer writer) {
      this.resource = resource;
      this.writer = writer;
    }

    FileObject getResource() {
      return resource;
    }

    Writer getWriter() {
      return writer;
    }
  }

  /* Based on code from com.twitter.common.args.apt; */
  private void writeResourceMapping(
      Set<String> contributingClassNames,
      FileObject file) {

    Resource resource = openResource("",
        "META-INF/compiler/resource-mappings/" + getClass().getName());
    if (resource != null) {
      PrintWriter writer = new PrintWriter(resource.getWriter());
      writer.printf("resources by class name:\n");
      writer.printf("%d items\n", contributingClassNames.size());
      try {
        for (String className : contributingClassNames) {
          writer.printf("%s -> %s\n", className, file.getName());
        }
      } finally {
        closeQuietly(writer);
      }
    }
  }

  private void closeQuietly(Closeable closeable) {
    try {
      closeable.close();
    } catch (IOException e) {
      log(Diagnostic.Kind.MANDATORY_WARNING, "Failed to close %s: %s", closeable, e);
    }
  }

  private Resource openResource(String packageName, String name) {
    FileObject resource = createResourceOrDie(packageName, name);
    return openResource(resource);
  }

  private Resource openResource(FileObject resource) {
    try {
      log(Diagnostic.Kind.NOTE, "Writing %s", resource.toUri());
      return new Resource(resource, resource.openWriter());
    } catch (IOException e) {
      if (!resource.delete()) {
        log(Diagnostic.Kind.WARNING, "Failed to clean up %s after a failing to open it for writing",
            resource.toUri());
      }
      log(Diagnostic.Kind.ERROR, "Failed to open resource file to store %s", resource.toUri());
      throw new RuntimeException(e);
    }
  }

  @Override public void init(ProcessingEnvironment processingEnvironment) {
    this.processingEnvironment = processingEnvironment;
    this.elementUtils = processingEnvironment.getElementUtils();
  }

  @Override public Set<String> getSupportedAnnotationTypes() {
    return ImmutableSet.of(Deprecated.class.getCanonicalName());
  }

  @Override public SourceVersion getSupportedSourceVersion() {
    return SourceVersion.latest();
  }

  @Override public boolean process(Set<? extends TypeElement> annotations,
      RoundEnvironment roundEnv) {
    if (roundEnv.processingOver()) {
      return false;
    }

    FileObject outputFile = createResourceOrDie("" /* no package */, REPORT_FILE_NAME);
    Closer closer = Closer.create();
    try {
      Set<String> typeNames = new HashSet<String>();
      PrintWriter writer = closer.register(new PrintWriter(outputFile.openWriter()));
      for (TypeElement appAnnotation : annotations) {
        Set<? extends Element> annotatedElements = roundEnv.getElementsAnnotatedWith(appAnnotation);
        Set<TypeElement> elements = ElementFilter.typesIn(annotatedElements);
        for (Element elem : elements) {
          if (!(elem instanceof TypeElement))
            continue;
          TypeElement typeElem = (TypeElement) elem;
          String typeName = elementUtils.getBinaryName(typeElem).toString();
          typeNames.add(typeName);
          writer.println(typeName);
        }
      }

      closer.close();

      writeResourceMapping(typeNames, outputFile);
      log(Diagnostic.Kind.NOTE, "Generated resource '%s'", outputFile.toUri());
    } catch (IOException e) {
      throw new RuntimeException(e);
    }

    return true;
  }

  private FileObject createResourceOrDie(String packageName, String fileName) {
    try {
      return processingEnvironment.getFiler().createResource(
          StandardLocation.CLASS_OUTPUT,
          packageName,
          fileName);
    } catch (IOException e) {
      throw new RuntimeException(e);
    }
  }

  private void log(Diagnostic.Kind category, String message, Object... args) {
    processingEnvironment.getMessager().printMessage(category, String.format(message, args));
  }
}
