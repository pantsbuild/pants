// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.annotation.processor;

import com.google.common.io.Closer;
import com.pants.examples.annotation.example.Example;
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

/**
 * A sample implementation of an annotation processor which looks for the @Example annotation on
 * class and prints out a list of all such classes to a file named <code>examples.txt</code>.
 */
public class ExampleProcessor extends AbstractProcessor {
  private final static String EXAMPLES_FILE_NAME = "examples.txt";
  private ProcessingEnvironment processingEnvironment = null;

  @Override public Set<String> getSupportedAnnotationTypes() {
    Set<String> result = new LinkedHashSet<String>();
    result.add(Example.class.getCanonicalName());
    return result;
  }

  @Override public SourceVersion getSupportedSourceVersion() {
    return SourceVersion.RELEASE_6;
  }

  @Override public boolean process(Set<? extends TypeElement> annotations,
      RoundEnvironment roundEnv) {
    if (roundEnv.processingOver()) {
      return false;
    }

    File outputFile = new File(EXAMPLES_FILE_NAME);
    Closer closer = Closer.create();

    try {
      PrintWriter writer = closer.register(new PrintWriter(new FileWriter(outputFile)));
      writer.println("{");
      for (TypeElement appAnnotation : annotations) {
        Set<? extends Element> annotatedElements = roundEnv.getElementsAnnotatedWith(appAnnotation);
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
    } catch (IOException e) {
      System.err.println("*** Couldn't write to " + outputFile.getAbsolutePath() + " " + e);
    }
    return true;
  }
}
