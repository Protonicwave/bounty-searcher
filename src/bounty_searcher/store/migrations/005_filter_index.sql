-- The count beside every page had no index to read, so it read the table.
--
-- A bounty row is mostly issue body: about 5.8KB of it against a couple of
-- hundred bytes of everything anything filters by. Measured over fifty
-- thousand rows with bodies that size, a count behind a language filter took
-- 150ms, behind a stars filter 175ms, and behind the unclaimed filter 66ms,
-- against a 25ms budget for the whole request. Each was scanning 320MB to
-- count rows it never reads a body from.
--
-- One covering index over the columns the filters test answers all of them
-- from about 3MB instead. It leads with `id` deliberately: an index is in the
-- order its columns are listed, and rowid order means the probes into
-- bounty_score that follow run forwards through that table rather than
-- jumping about it. That is worth roughly half the remaining time on the
-- filters that match a lot of rows.
--
-- Ordering is not what this is for. Each sort still reads the index built for
-- it, and the unfiltered count still reads the narrower bounty_amount.

CREATE INDEX IF NOT EXISTS bounty_filters ON bounty(
    id,
    language,
    stars,
    created_at,
    amount_minor,
    first_seen_at,
    changed_at,
    claim_reason
);
