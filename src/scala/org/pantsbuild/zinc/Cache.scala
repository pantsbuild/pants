/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.lang.ref.SoftReference
import java.util.{ LinkedHashMap, Map => JMap }
import scala.collection.breakOut
import scala.collection.JavaConverters._

/**
 * A simple LRU cache using soft references.
 */
object Cache {
  final val DefaultInitialSize = 8

  case class Stats(size: Int, hits: Int, misses: Int)

  def apply[K, V](maxSize: Int): Cache[K, V] =
    new Cache[K, V](maxSize min DefaultInitialSize, maxSize)
}

/**
 * A simple LRU cache using soft references.
 */
class Cache[K, V](initialSize: Int, val maxSize: Int) {
  private[this] val cache = createMap[K, V](initialSize, maxSize)

  private[this] var hits = 0
  private[this] var misses = 0

  type Entry = JMap.Entry[K, SoftReference[V]]

  /**
   * Get a value from the cache.
   * Also requires a call-by-name argument for creating the value on cache miss.
   */
  def get(key: K)(value: => V): V = synchronized {
    cache.get(key) match {
      case null => missed(key, value)
      case ref  => ref.get match {
        case null   => missed(key, value)
        case cached => hit(key, cached)
      }
    }
  }

  /**
   * Put or update a value in the cache.
   */
  def put(key: K, value: V): V = synchronized {
    cache.put(key, new SoftReference(value))
    value
  }

  /**
   * Clear the cache.
   */
  def clear(): Unit = synchronized {
    cache.clear()
  }

  /**
   * Get all (key, value) pairs currently cached.
   */
  def entries(): Set[(K, V)] = synchronized {
    def kv(e: Entry) = Option(e.getValue.get) map (e.getKey -> _)
    cache.entrySet.asScala.flatMap(kv)(breakOut)
  }

  /**
   * Get size, hits, and misses stats for the cache.
   */
  def stats(): Cache.Stats = synchronized {
    Cache.Stats(cache.size, hits, misses)
  }

  private[this] def missed(key: K, value: V): V = {
    misses += 1
    put(key, value)
  }

  private[this] def hit(key: K, value: V): V = {
    hits += 1
    value
  }

  private[this] def createMap[A, B](initial: Int, max: Int): LinkedHashMap[A, SoftReference[B]] =
    new LinkedHashMap[A, SoftReference[B]](initial, 0.75f, true) {
      override def removeEldestEntry(eldest: JMap.Entry[A, SoftReference[B]]): Boolean = size > max
    }
}
