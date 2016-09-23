// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.lang.reflect.Method;
import java.util.Collection;
import java.util.Optional;

import com.google.common.base.Preconditions;
import com.google.common.cache.CacheBuilder;
import com.google.common.cache.CacheLoader;
import com.google.common.cache.LoadingCache;
import com.google.common.collect.Iterables;

/**
 * Takes strings passed to the command line representing packages or individual methods
 * and returns a parsed Spec.  Each Spec represents a single class, so individual methods
 * are added into each spec
 */
class SpecParser {
  private final Iterable<String> testSpecStrings;
  private final LoadingCache<Class<?>, Spec> specs =
      CacheBuilder.newBuilder().build(CacheLoader.from(Spec::new));

  /**
   * Parses the list of incoming test specs from the command line.
   * <p>
   * Expects a list of string specs which can be represented as one of:
   * <ul>
   *   <li>package.className</li>
   *   <li>package.className#methodName</li>
   * </ul>
   * Note that each class or method will only be executed once, no matter how many times it is
   * present in the list.
   * </p>
   * <p>
   * It is illegal to pass a spec with just the className if there are also individual methods
   * present in the list within the same class.
   * </p>
   */
  // TODO(zundel): This could easily be extended to allow a regular expression in the spec
  SpecParser(Iterable<String> testSpecStrings) {
    Preconditions.checkArgument(!Iterables.isEmpty(testSpecStrings));
    this.testSpecStrings = testSpecStrings;
  }

  /**
   * Parse the specs passed in to the constructor.
   *
   * @return List of parsed specs
   * @throws SpecException when there is a problem parsing specs
   */
  Collection<Spec> parse() throws SpecException {
    for (String specString : testSpecStrings) {
      if (specString.indexOf('#') >= 0) {
        addMethod(specString);
      } else {
        Optional<Spec> spec = getOrCreateSpec(specString, specString);
        spec.ifPresent(s -> {
          if (specs.asMap().containsKey(s.getSpecClass()) && !s.getMethods().isEmpty()) {
            throw new SpecException(specString,
                "Request for entire class already requesting individual methods");
          }
        });
      }
    }
    return specs.asMap().values();
  }

  /**
   * Creates or returns an existing Spec that corresponds to the className parameter.
   *
   * @param className The class name already parsed out of specString
   * @param specString  A spec string described in {@link SpecParser}
   * @return a present Spec instance on success, absent if this spec string should be ignored
   * @throws SpecException if the method passed in is not an executable test method
   */
  private Optional<Spec> getOrCreateSpec(String className, String specString) throws SpecException {
    try {
      Class<?> clazz = getClass().getClassLoader().loadClass(className);
      if (Util.isTestClass(clazz)) {
        return Optional.of(specs.getUnchecked(clazz));
      } else {
        return Optional.empty();
      }
    } catch (ClassNotFoundException | NoClassDefFoundError e) {
      throw new SpecException(specString,
          String.format("Class %s not found in classpath.", className), e);
    } catch (LinkageError e) {
      // Any of a number of runtime linking errors can occur when trying to load a class,
      // fail with the test spec so the class failing to link is known.
      throw new SpecException(specString,
          String.format("Error linking %s.", className), e);
      // See the comment below for justification.
    } catch (RuntimeException e) {
      // The class may fail with some variant of RTE in its static initializers, trap these
      // and dump the bad spec in question to help narrow down issue.
      throw new SpecException(specString,
          String.format("Error initializing %s.",className), e);
    }
  }

  /**
   * Handle a spec that looks like package.className#methodName
   */
  private void addMethod(String specString) throws SpecException {
    String[] results = specString.split("#");
    if (results.length != 2) {
      throw new SpecException(specString, "Expected only one # in spec");
    }
    String className = results[0];
    String methodName = results[1];

    Optional<Spec> spec = getOrCreateSpec(className, specString);
    spec.ifPresent(s -> {
      for (Method clazzMethod : s.getSpecClass().getMethods()) {
        if (clazzMethod.getName().equals(methodName)) {
          Spec specWithMethod = s.addMethod(methodName);
          specs.put(s.getSpecClass(), specWithMethod);
          return;
        }
      }
      // TODO(John Sirois): Introduce an Either type to make this function total.
      throw new SpecException(specString,
          String.format("Method %s not found in class %s", methodName, className));
    });
  }
}
