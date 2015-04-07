// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.annotation.processor;

import com.google.common.collect.ImmutableSet;
import com.google.common.io.Closer;
import org.pantsbuild.example.annotation.example.Example;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;
import javax.annotation.processing.AbstractProcessor;
import javax.annotation.processing.ProcessingEnvironment;
import javax.annotation.processing.RoundEnvironment;
import javax.lang.model.SourceVersion;
import javax.lang.model.element.AnnotationMirror;
import javax.lang.model.element.AnnotationValue;
import javax.lang.model.element.Element;
import javax.lang.model.element.ExecutableElement;
import javax.lang.model.element.TypeElement;
import javax.lang.model.util.ElementFilter;
import javax.tools.Diagnostic;
import javax.tools.FileObject;
import javax.tools.StandardLocation;

/**
 * A sample implementation of an annotation processor which looks for the @Example annotation on
 * class and prints out a list of all such classes to a file named <code>examples.txt</code>.
 */
public class ExampleProcessor extends AbstractProcessor {
  private static final String EXAMPLES_FILE_NAME = "examples.txt";

  private ProcessingEnvironment processingEnvironment = null;

  @Override public void init(ProcessingEnvironment processingEnvironment) {
    this.processingEnvironment = processingEnvironment;
  }

  @Override public Set<String> getSupportedAnnotationTypes() {
    return ImmutableSet.of(Example.class.getCanonicalName());
  }

  @Override public SourceVersion getSupportedSourceVersion() {
    return SourceVersion.latest();
  }

  @Override public boolean process(Set<? extends TypeElement> annotations,
      RoundEnvironment roundEnv) {
    if (roundEnv.processingOver()) {
      return false;
    }

    FileObject outputFile = createResource("" /* no package */, EXAMPLES_FILE_NAME);
    if (outputFile != null) {
      Closer closer = Closer.create();
      try {
        PrintWriter writer = closer.register(new PrintWriter(outputFile.openWriter()));
        writer.println("{");
        for (TypeElement appAnnotation : annotations) {
          Set<? extends Element> annotatedElements =
              roundEnv.getElementsAnnotatedWith(appAnnotation);
          Set<TypeElement> exampleElements = ElementFilter.typesIn(annotatedElements);
          for (Element elem : exampleElements) {
            String typeName = elem.getSimpleName().toString();
            for (AnnotationMirror mirror : elem.getAnnotationMirrors()) {
              String n =
                  ((TypeElement) mirror.getAnnotationType().asElement()).getQualifiedName()
                      .toString();
              if (Example.class.getCanonicalName().equals(n)) {
                Map<? extends ExecutableElement, ? extends AnnotationValue> values =
                    mirror.getElementValues();
                for (ExecutableElement key : values.keySet()) {
                  if ("value".equals(key.getSimpleName().toString())) {
                    String exampleValue = (String) values.get(key).getValue();
                    if (exampleValue != null) {
                      writer.println(
                          "  {'type' : '" + typeName + "', 'value': '" + exampleValue + "'},");
                    }
                  }
                }
              }
            }
          }
          writer.println("}\n");
        }
        closer.close();
        log(Diagnostic.Kind.NOTE, "Generated resource '%s'", outputFile.toUri());
      } catch (IOException e) {
        error("Couldn't write to '%s': %s", outputFile.toUri(), e);
      }
    }
    return true;
  }

  private FileObject createResource(String packageName, String fileName) {
    try {
      return processingEnvironment.getFiler().createResource(
          StandardLocation.CLASS_OUTPUT,
          packageName,
          fileName);
    } catch (IOException e) {
      error("Failed to create resource for package: '%s' with name: '%s': %s", packageName,
          fileName, e);
      return null;
    }
  }

  private void error(String message, Object... args) {
    log(Diagnostic.Kind.ERROR, message, args);
  }

  private void log(Diagnostic.Kind category, String message, Object... args) {
    processingEnvironment.getMessager().printMessage(category, String.format(message, args));
  }
}
