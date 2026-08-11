-- The CLI now scans into the corpus and reads back out of it, so the two
-- tables it kept for itself have nothing left to hold. "Seen" is first_seen_at
-- on bounty, and the repository cache is repo_meta.

DROP TABLE IF EXISTS seen;
DROP TABLE IF EXISTS repo_cache;
