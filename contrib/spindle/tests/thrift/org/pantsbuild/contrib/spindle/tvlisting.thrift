# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This file was copied with significant modifications
# from the spindle project (github.com/foursquare/spindle)
# which is also Apache 2 licensed.

namespace java org.pantsbuild.contrib.spindle

typedef string DateTime // String in the format YYYY-MM-DD HH:MM:SS

// newtype test
// Note that `bson:ObjectId` means we depend on org.mongodb:bson
typedef binary (enhanced_types="bson:ObjectId") ObjectId
typedef ObjectId MyObjectId (new_type="true")
typedef string MyString (new_type="true")
typedef i64 MyLong (new_type="true")


struct TvListingEntry {
  1: optional ObjectId contentid (wire_name="_id")
  2: optional DateTime startTime (wire_name="st")
  3: optional DateTime endTime (wire_name="et")
  4: optional i64 rating
} (primary_key="contentid"
   mongo_collection="tv")

typedef list<TvListingEntry> TvListing
