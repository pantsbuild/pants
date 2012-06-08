/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import java.lang.ref.SoftReference
import java.util.{ LinkedHashMap, Map }

object Cache {
  final val DefaultInitialSize = 8

  case class Stats(size: Int, hits: Int, misses: Int)

  def apply[K, V](maxSize: Int): Cache[K, V] =
    new Cache[K, V](maxSize min DefaultInitialSize, maxSize)
}

class Cache[K, V](initialSize: Int, val maxSize: Int) {
  private[this] val cache = createMap[K, V](initialSize, maxSize)

  private[this] var hits = 0
  private[this] var misses = 0

  def get(key: K)(value: => V): V = synchronized {
    cache.get(key) match {
      case null => missed(key, value)
      case ref => ref.get match {
        case null => missed(key, value)
        case cached => hit(key, cached)
      }
    }
  }

  def put(key: K, value: V): V = synchronized {
    cache.put(key, new SoftReference(value))
    value
  }

  def clear(): Unit = synchronized {
    cache.clear()
  }

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
      override def removeEldestEntry(eldest: Map.Entry[A, SoftReference[B]]): Boolean = size > max
    }
}
