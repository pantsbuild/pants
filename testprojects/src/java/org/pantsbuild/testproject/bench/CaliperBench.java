package org.pantsbuild.testproject.bench;

import com.google.caliper.SimpleBenchmark;

import java.lang.Integer;
import java.util.HashSet;
import java.util.Set;

public class CaliperBench extends SimpleBenchmark {

  static final int ADDS_PER_REP = 1000;

  final Set<Integer> set = new HashSet<Integer>();

  public void timeHashSetAdd(int reps) {
    for (int repNo = 0; repNo < reps; repNo++) {
      for (int i = 0; i < ADDS_PER_REP; i++) {
        set.add(i);
      }
    }
  }
}