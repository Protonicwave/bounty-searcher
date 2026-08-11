/**
 * Enough markdown for an issue body, parsed into spans that remember where
 * they came from.
 *
 * There is no HTML anywhere in here on purpose. The body is somebody else's
 * text, and the only sanitiser that cannot be got round is one that never
 * builds markup in the first place: this produces data, the renderer produces
 * elements, and a `<script>` in an issue body is a run of characters that ends
 * up on screen as a run of characters.
 *
 * Every span carries the offset of its text in the source, because the payout
 * is highlighted at the exact offsets the parser recorded when it read the
 * figure, and a round trip through HTML would lose them.
 */

export type SpanKind = 'text' | 'code' | 'strong' | 'em' | 'link'

export interface Span {
  kind: SpanKind
  text: string
  /** Where `text` starts in the source, so a highlight can be placed on it. */
  start: number
  /** Set on links only, and only ever http or https. */
  href?: string
}

export type Block =
  | { kind: 'paragraph'; spans: Span[] }
  | { kind: 'heading'; level: number; spans: Span[] }
  | { kind: 'quote'; spans: Span[] }
  | { kind: 'list'; ordered: boolean; items: Span[][] }
  | { kind: 'code'; text: string }

/**
 * Inline markup, in one pass.
 *
 * Deliberately flat: bold inside a link is vanishingly rare in an issue and
 * nesting would cost the offsets, which are the reason this exists.
 */
const INLINE = new RegExp(
  [
    '(`+)([\\s\\S]*?)\\1', //            1,2  code span
    // A target may hold one level of brackets, which plenty of real links do,
    // and may be followed by a title nobody displays.
    '\\[([^\\]]*)\\]\\(\\s*((?:[^()\\s]|\\([^()\\s]*\\))*)(?:\\s+"[^"]*")?\\s*\\)', // 3,4
    '\\*\\*([\\s\\S]+?)\\*\\*', //       5    strong
    '__([\\s\\S]+?)__', //               6    strong
    '\\*([^*\\n]+?)\\*', //              7    emphasis
    '_([^_\\n]+?)_', //                  8    emphasis
    '<(https?://[^>\\s]+)>', //          9    angle autolink
    '(https?://[^\\s<>()\\[\\]]+)', //   10   bare autolink
  ].join('|'),
  'g',
)

/** Anything that is not plainly http or https is not a link we will render. */
function safeHref(href: string): string | null {
  return /^https?:\/\//i.test(href) ? href : null
}

function text(value: string, start: number): Span {
  return { kind: 'text', text: value, start }
}

/** One run of source into spans. `base` is where the run sits in the body. */
export function parseInline(source: string, base = 0): Span[] {
  const spans: Span[] = []
  let last = 0
  INLINE.lastIndex = 0

  for (let m = INLINE.exec(source); m !== null; m = INLINE.exec(source)) {
    if (m.index > last) spans.push(text(source.slice(last, m.index), base + last))
    const at = base + m.index

    if (m[2] !== undefined) {
      spans.push({ kind: 'code', text: m[2], start: at + (m[1]?.length ?? 1) })
    } else if (m[3] !== undefined && m[4] !== undefined) {
      const href = safeHref(m[4])
      spans.push(
        href === null
          ? // A link nobody should follow still has words worth reading.
            text(m[3], at + 1)
          : { kind: 'link', text: m[3] || href, href, start: at + 1 },
      )
    } else if (m[5] !== undefined) {
      spans.push({ kind: 'strong', text: m[5], start: at + 2 })
    } else if (m[6] !== undefined) {
      spans.push({ kind: 'strong', text: m[6], start: at + 2 })
    } else if (m[7] !== undefined) {
      spans.push({ kind: 'em', text: m[7], start: at + 1 })
    } else if (m[8] !== undefined) {
      spans.push({ kind: 'em', text: m[8], start: at + 1 })
    } else if (m[9] !== undefined) {
      spans.push({ kind: 'link', text: m[9], href: m[9], start: at + 1 })
    } else if (m[10] !== undefined) {
      spans.push({ kind: 'link', text: m[10], href: m[10], start: at })
    }
    last = m.index + m[0].length
  }

  if (last < source.length) spans.push(text(source.slice(last), base + last))
  return spans
}

const FENCE = /^\s*(?:```|~~~)/
const HEADING = /^(#{1,6})\s+(.*)$/
const QUOTE = /^\s{0,3}>\s?(.*)$/
const BULLET = /^\s*[-*+]\s+(.*)$/
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/

interface Line {
  text: string
  start: number
}

function lines(source: string): Line[] {
  const out: Line[] = []
  let start = 0
  for (const line of source.split('\n')) {
    out.push({ text: line, start })
    start += line.length + 1
  }
  return out
}

/** Several lines of one paragraph, joined the way markdown joins them. */
function joined(run: Line[]): Span[] {
  return run.flatMap((line, i) => [
    ...(i > 0 ? [text(' ', line.start - 1)] : []),
    ...parseInline(line.text, line.start),
  ])
}

/**
 * The body, as blocks.
 *
 * The subset is what issues are actually written in: paragraphs, fenced code,
 * headings, quotes, and both kinds of list. Anything else arrives as the text
 * it is, which is the right failure: unreadable beats wrong.
 */
export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = []
  const all = lines(source.replace(/\r\n?/g, '\n'))
  let paragraph: Line[] = []

  const flush = () => {
    if (paragraph.length > 0) blocks.push({ kind: 'paragraph', spans: joined(paragraph) })
    paragraph = []
  }

  for (let i = 0; i < all.length; i++) {
    const line = all[i]
    if (!line) continue

    if (FENCE.test(line.text)) {
      flush()
      const body: string[] = []
      i += 1
      while (i < all.length && !FENCE.test(all[i]?.text ?? '')) {
        body.push(all[i]?.text ?? '')
        i += 1
      }
      blocks.push({ kind: 'code', text: body.join('\n') })
      continue
    }

    const heading = HEADING.exec(line.text)
    if (heading?.[1] !== undefined && heading[2] !== undefined) {
      flush()
      blocks.push({
        kind: 'heading',
        level: heading[1].length,
        spans: parseInline(heading[2], line.start + heading[1].length + 1),
      })
      continue
    }

    const bullet = BULLET.exec(line.text)
    const numbered = NUMBERED.exec(line.text)
    if (bullet ?? numbered) {
      flush()
      const ordered = bullet === null
      const items: Span[][] = []
      while (i < all.length) {
        const at = all[i]
        if (!at) break
        const item = ordered ? NUMBERED.exec(at.text) : BULLET.exec(at.text)
        if (item?.[1] === undefined) break
        items.push(parseInline(item[1], at.start + at.text.indexOf(item[1])))
        i += 1
      }
      i -= 1
      blocks.push({ kind: 'list', ordered, items })
      continue
    }

    const quote = QUOTE.exec(line.text)
    if (quote?.[1] !== undefined) {
      flush()
      const run: Line[] = []
      while (i < all.length) {
        const at = all[i]
        if (!at) break
        const more = QUOTE.exec(at.text)
        if (more?.[1] === undefined) break
        run.push({ text: more[1], start: at.start + at.text.indexOf(more[1]) })
        i += 1
      }
      i -= 1
      blocks.push({ kind: 'quote', spans: joined(run) })
      continue
    }

    if (line.text.trim() === '') flush()
    else paragraph.push(line)
  }

  flush()
  return blocks
}

export interface Piece {
  text: string
  /** True for the run the payout was read from, which is marked in place. */
  marked: boolean
}

/**
 * One span split around the payout, if the payout is inside it.
 *
 * The figure is highlighted where it was found rather than searched for again,
 * because the same characters often appear twice in a body and only one of
 * them is the one that was believed.
 */
export function highlight(
  span: Span,
  range: { start: number; end: number } | null,
): Piece[] {
  const end = span.start + span.text.length
  if (range === null || range.end <= span.start || range.start >= end) {
    return [{ text: span.text, marked: false }]
  }
  const from = Math.max(range.start, span.start) - span.start
  const to = Math.min(range.end, end) - span.start
  return [
    { text: span.text.slice(0, from), marked: false },
    { text: span.text.slice(from, to), marked: true },
    { text: span.text.slice(to), marked: false },
  ].filter((piece) => piece.text !== '')
}

/** Which line of the source an offset falls on, counting from one. */
export function lineOf(source: string, offset: number): number {
  let line = 1
  for (let i = 0; i < offset && i < source.length; i++) {
    if (source[i] === '\n') line += 1
  }
  return line
}
