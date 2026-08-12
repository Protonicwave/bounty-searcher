/**
 * The wire format, mirroring `api/schemas.py`.
 *
 * Hand-written rather than generated: the surface is small, and a type that is
 * read by a person is worth more here than one that is regenerated. Timestamps
 * arrive as ISO 8601 strings and stay strings until a formatter is asked for
 * them. Money arrives as minor units and is never a float.
 */

export type AmountField = 'label' | 'title' | 'body' | 'comment'

export type Confidence = 'high' | 'medium' | 'low'

export type TriageStatus =
  | 'new'
  | 'shortlisted'
  | 'dismissed'
  | 'applied'
  | 'snoozed'

/** The six the score is made of. The rail draws one segment per component. */
export type ScoreComponent =
  | 'payout'
  | 'language'
  | 'effort'
  | 'freshness'
  | 'competition'
  | 'repository'

export type SortKey = 'score' | 'newest' | 'payout'

export type ViewName = 'tonight' | 'payday' | 'changed' | 'all'

export type Budget = 'search' | 'core'

export type RunStatus = 'running' | 'done' | 'failed' | 'interrupted'

export interface Provenance {
  field: AmountField
  pattern: string
  start: number
  end: number
  text: string
}

export interface Amount {
  minor_units: number
  currency: string
  confidence: Confidence
  provenance: Provenance
}

export interface Component {
  component: ScoreComponent
  value: number
  /** What this component could have reached, so a segment draws to scale. */
  maximum: number
}

export interface Score {
  total: number
  base: number
  components: Component[]
  weights_hash: string
}

export interface Triage {
  status: TriageStatus
  snooze_until: string | null
  updated_at: string | null
}

export interface BountyRow {
  id: number
  key: string
  source: string
  repo: string
  number: number
  title: string
  url: string
  state: string
  labels: string[]
  comments: number
  assignee: string | null
  language: string | null
  stars: number | null
  is_fork: boolean
  claim_reason: string | null
  suspect_reason: string | null
  amount: Amount | null
  created_at: string
  updated_at: string
  first_seen_at: string | null
  changed_at: string | null
  is_new: boolean
  is_changed: boolean
  score: Score
  triage: Triage
}

export interface BountyDetail extends BountyRow {
  body: string
}

export interface BountyPage {
  rows: BountyRow[]
  /** How many matched, not how many are on this page. */
  total: number
  next_cursor: string | null
  view: ViewName
  sort: SortKey
}

/** What a transition returns: the rows it moved, and the token that reverses it. */
export interface TriageResult {
  bounty_ids: number[]
  status: TriageStatus
  undo_token: string
}

export interface UndoResult {
  bounty_ids: number[]
}

export interface ScanStarted {
  run_id: number
  /** True when an unfinished sweep was picked up rather than a new one begun. */
  resumed: boolean
}

export interface Bucket {
  budget: Budget
  limit: number
  remaining: number
  reset_at: string
}

export interface Quota {
  search: Bucket
  core: Bucket
  paused_until: string | null
}

export interface Counts {
  total: number
  priced: number
  suspect: number
  by_status: Partial<Record<TriageStatus, number>>
}

export interface Scan {
  run_id: number
  status: RunStatus
  started_at: string
  finished_at: string | null
  planned: number
  completed: number
  failed: number
  new_bounties: number
  error: string | null
  running: boolean
}

export interface View {
  name: ViewName
  title: string
  description: string
}

export interface Meta {
  version: string
  counts: Counts
  views: View[]
  last_scan: Scan | null
  /** Null until a sweep has run in this process. Nothing else can know it. */
  quota: Quota | null
}
