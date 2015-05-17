/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import com.google.common.cache

import java.util.concurrent.Callable

import scala.collection.JavaConverters._

/**
 * An LRU cache using soft references.
 */
object Cache {
  final val DefaultInitialSize = 8

  def apply[K<:AnyRef, V<:AnyRef](maxSize: Int): cache.Cache[K, V] =
    cache.CacheBuilder.newBuilder()
      .softValues()
      .initialCapacity(maxSize min DefaultInitialSize)
      .maximumSize(maxSize)
      .build()

  /**
   * Implicitly add conveniences to the guava Cache.
   *
   * NB: This should become a value class after we're on scala 2.11.x: see SI-8011.
   */
  implicit class Implicits[K, V](val c: cache.Cache[K, V]) {
    def getOrElseUpdate(key: K)(value: => V): V =
      c.get(key, new Callable[V] { def call = value })

    def entries: Seq[(K,V)] =
      c.asMap.entrySet.asScala.toSeq.map { e => e.getKey -> e.getValue }
  }
}
