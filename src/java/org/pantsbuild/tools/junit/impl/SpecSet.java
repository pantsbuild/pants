package org.pantsbuild.tools.junit.impl;

import com.google.common.collect.ImmutableSet;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Set;

class SpecSet {
  private final Set<Spec> specs;
  private final Concurrency defaultConcurrency;

  public SpecSet(Collection<Spec> allSpecs, Concurrency defaultConcurrency) {
    this.specs = new LinkedHashSet(allSpecs);
    this.defaultConcurrency = defaultConcurrency;
  }

  /**
   * Remove and return all specs that match the specfied Concurrency parameter and have no
   * separate test methods defined.
   */
  public SpecSet extract(Concurrency concurrencyFilter) {
    Set<Spec> results = new LinkedHashSet<Spec>();
    for (Spec spec : specs) {
      if (spec.getMethods().isEmpty() &&
          spec.getConcurrency(defaultConcurrency).equals(concurrencyFilter)) {
        results.add(spec);
      }
    }
    specs.removeAll(results);
    return new SpecSet(results, defaultConcurrency);
  }

  public Set<Spec> specs() {
    return ImmutableSet.copyOf(specs);
  }

  public  Class<?>[] classes() {
    Class<?>[] classes = new Class<?>[specs.size()];
    int index = 0;
    for (Spec spec: specs) {
      classes[index++] = spec.getSpecClass();
    }
    return classes;
  }
}