// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.annotation.processorwithdep.processor;

import org.pantsbuild.testproject.annotation.processorwithdep.hellomaker.HelloMaker;
import com.squareup.javapoet.JavaFile;
import com.squareup.javapoet.MethodSpec;
import com.squareup.javapoet.TypeSpec;
import java.io.IOException;
import java.io.PrintWriter;
import java.io.Writer;
import java.util.Collections;
import java.util.Set;
import javax.annotation.processing.AbstractProcessor;
import javax.annotation.processing.ProcessingEnvironment;
import javax.annotation.processing.RoundEnvironment;
import javax.lang.model.SourceVersion;
import javax.lang.model.element.Element;
import javax.lang.model.element.Modifier;
import javax.lang.model.element.TypeElement;
import javax.lang.model.util.ElementFilter;
import javax.lang.model.util.Elements;
import javax.tools.Diagnostic;
import javax.tools.Diagnostic.Kind;
import javax.tools.JavaFileObject;

/**
 * A sample implementation of an annotation processor which creates a "Hello World" class.
 */
public class ProcessorWithDep extends AbstractProcessor {
  TypeSpec unused = TypeSpec.enumBuilder("PantsProblemCauser")
      .addEnumConstant("BAR")
      .build();
  private ProcessingEnvironment processingEnvironment = null;
  private Elements elementUtils;

  private void writeHelloWorld(String packageName, String classPrefix) throws IOException{
    MethodSpec main = MethodSpec.methodBuilder("main")
        .addModifiers(Modifier.PUBLIC, Modifier.STATIC)
        .returns(void.class)
        .addParameter(String[].class, "args")
        .addStatement("$T.out.println($S)", System.class, "Hello, JavaPoet!")
        .build();

    String className = classPrefix + "_HelloWorld";
    TypeSpec helloWorld = TypeSpec.classBuilder(className)
        .addModifiers(Modifier.PUBLIC, Modifier.FINAL)
        .addMethod(main)
        .build();

    JavaFile javaFile = JavaFile.builder(packageName, helloWorld)
        .build();

    JavaFileObject f = processingEnvironment.getFiler().createSourceFile(
        String.format("%s.%s", packageName, className));
    Writer w = f.openWriter();
    javaFile.writeTo(w);
    w.close();
  }

  @Override public void init(ProcessingEnvironment processingEnvironment) {
    this.processingEnvironment = processingEnvironment;
    this.elementUtils = processingEnvironment.getElementUtils();
    // Make a reference to the 3rdparty library in the initialization of the annotation processor
    // to tickle a bug in pants
    TypeSpec.enumBuilder("PantsProblemCauser")
        .addEnumConstant("BAR")
        .build();
  }

  @Override public Set<String> getSupportedAnnotationTypes() {
    return Collections.singleton(HelloMaker.class.getCanonicalName());
  }

  @Override public SourceVersion getSupportedSourceVersion() {
    return SourceVersion.latest();
  }

  @Override public boolean process(Set<? extends TypeElement> annotations,
      RoundEnvironment roundEnv) {
    if (roundEnv.processingOver()) {
      return false;
    }

    PrintWriter writer = null;

    try {
      for (TypeElement appAnnotation : annotations) {
        Set<? extends Element> annotatedElements = roundEnv.getElementsAnnotatedWith(appAnnotation);
        Set<TypeElement> elements = ElementFilter.typesIn(annotatedElements);
        for (Element elem : elements) {
          if (!(elem instanceof TypeElement))
            continue;
          TypeElement typeElem = (TypeElement) elem;
          String packageName = elementUtils.getPackageOf(typeElem).getQualifiedName().toString();
          String typeName = typeElem.getSimpleName().toString();
          writeHelloWorld(packageName, typeName);
        }
      }
    } catch (IOException ex) {
      log(Kind.ERROR, "Problem writing source file.", ex);
      throw new RuntimeException(ex);
    } finally {
      if (writer != null) {
        writer.close();
      }
    }
    return true;
  }

  private void log(Diagnostic.Kind category, String message, Object... args) {
    processingEnvironment.getMessager().printMessage(category, String.format(message, args));
  }
}
