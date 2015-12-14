/**
 * Copyright (C) 2015 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.cache

import com.google.common.{cache => gcache}

import java.util.concurrent.Callable

import scala.collection.JavaConverters._

/**
 * An LRU cache using soft references.
 */
object Cache {
  final val DefaultInitialSize = 8

  def apply[K<:AnyRef, V<:AnyRef](maxSize: Int): gcache.Cache[K, V] =
    gcache.CacheBuilder.newBuilder()
      .softValues()
      .initialCapacity(maxSize min DefaultInitialSize)
      .maximumSize(maxSize)
      .build()

  /**
   * Implicitly add conveniences to the guava Cache.
   *
   * NB: This should become a value class after we're on scala 2.11.x: see SI-8011.
   */
  implicit class Implicits[K, V](val c: gcache.Cache[K, V]) {
    def getOrElseUpdate(key: K)(value: => V): V =
      c.get(key, new Callable[V] { def call = value })

    def entries: Seq[(K,V)] =
      c.asMap.entrySet.asScala.toSeq.map { e => e.getKey -> e.getValue }
  }
}
