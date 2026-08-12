import { describe, expect, it } from 'vitest'

import { highlight, lineOf, parseInline, parseMarkdown } from './markdown'
import type { Block, Span } from './markdown'

/** What a span points at in the source, which is the whole premise of this. */
function pointsAt(source: string, span: Span): string {
  return source.slice(span.start, span.start + span.text.length)
}

function spansOf(block: Block | undefined): Span[] {
  if (!block) return []
  return 'spans' in block ? block.spans : []
}

describe('parseInline', () => {
  it('reads code spans, links and emphasis out of a line', () => {
    const source = 'call `go()` in [the docs](https://example.com), **now**'
    const spans = parseInline(source)
    expect(spans.map((s) => s.kind)).toEqual([
      'text',
      'code',
      'text',
      'link',
      'text',
      'strong',
    ])
    expect(spans[3]?.href).toBe('https://example.com')
  })

  it('leaves every span pointing at the source it came from', () => {
    const source = 'a `code` and **bold** and [text](https://example.com)'
    for (const span of parseInline(source)) {
      expect(pointsAt(source, span)).toBe(span.text)
    }
  })

  it('keeps offsets when the run starts part way into the body', () => {
    const source = 'line one\npays `$500` today'
    const spans = parseInline('pays `$500` today', 9)
    expect(pointsAt(source, spans[1] as Span)).toBe('$500')
  })

  it('refuses a scheme nobody should follow, and keeps the words', () => {
    const spans = parseInline('[click](javascript:alert(1))')
    expect(spans[0]?.kind).toBe('text')
    expect(spans[0]?.text).toBe('click')
    expect(spans[0]?.href).toBeUndefined()
  })

  it('keeps a bracket that belongs to the target, and drops a title', () => {
    expect(parseInline('[x](https://example.com/a_(b) "t")')[0]).toMatchObject({
      kind: 'link',
      href: 'https://example.com/a_(b)',
      text: 'x',
    })
  })

  it('links a bare url and one in angle brackets', () => {
    expect(parseInline('see https://example.com/x now')[1]).toMatchObject({
      kind: 'link',
      href: 'https://example.com/x',
    })
    expect(parseInline('<https://example.com>')[0]).toMatchObject({
      kind: 'link',
      href: 'https://example.com',
    })
  })

  it('treats markup it does not know as the text it is', () => {
    const spans = parseInline('<script>alert(1)</script>')
    expect(spans).toHaveLength(1)
    expect(spans[0]).toMatchObject({ kind: 'text', text: '<script>alert(1)</script>' })
  })
})

describe('parseMarkdown', () => {
  it('splits paragraphs on blank lines and joins the lines within one', () => {
    const blocks = parseMarkdown('one\ntwo\n\nthree')
    expect(blocks).toHaveLength(2)
    expect(spansOf(blocks[0]).map((s) => s.text)).toEqual(['one', ' ', 'two'])
  })

  it('reads a fenced block as the text inside it, markup and all', () => {
    const blocks = parseMarkdown('before\n\n```ts\nconst a = `x`\n```\n\nafter')
    expect(blocks[1]).toEqual({ kind: 'code', text: 'const a = `x`' })
  })

  it('collects consecutive bullets into one list', () => {
    const blocks = parseMarkdown('- first\n- second\n\nafter')
    expect(blocks[0]).toMatchObject({ kind: 'list', ordered: false })
    const list = blocks[0]
    expect(list?.kind === 'list' && list.items).toHaveLength(2)
  })

  it('tells a numbered list from a bulleted one', () => {
    const blocks = parseMarkdown('1. first\n2. second')
    expect(blocks[0]).toMatchObject({ kind: 'list', ordered: true })
  })

  it('reads headings and quotes', () => {
    const blocks = parseMarkdown('## Steps\n\n> quoted line')
    expect(blocks[0]).toMatchObject({ kind: 'heading', level: 2 })
    expect(spansOf(blocks[0])[0]?.text).toBe('Steps')
    expect(blocks[1]?.kind).toBe('quote')
  })

  it('keeps offsets across blocks, so a payout is found where it was read', () => {
    const source = '## Steps\n\n- pay is $500\n\nthanks'
    const list = parseMarkdown(source)[1]
    const span = list?.kind === 'list' ? list.items[0]?.[0] : undefined
    expect(span && pointsAt(source, span)).toBe('pay is $500')
  })

  it('survives a body that is only whitespace', () => {
    expect(parseMarkdown('')).toEqual([])
    expect(parseMarkdown('\n\n  \n')).toEqual([])
  })
})

describe('highlight', () => {
  const span: Span = { kind: 'text', text: 'a bounty of $500 here', start: 100 }

  it('splits the span around the run that was read', () => {
    expect(highlight(span, { start: 112, end: 116 })).toEqual([
      { text: 'a bounty of ', marked: false },
      { text: '$500', marked: true },
      { text: ' here', marked: false },
    ])
  })

  it('leaves a span the payout is not in alone', () => {
    expect(highlight(span, { start: 0, end: 4 })).toEqual([
      { text: 'a bounty of $500 here', marked: false },
    ])
    expect(highlight(span, null)).toHaveLength(1)
  })

  it('marks a run that starts the span without an empty piece before it', () => {
    expect(highlight(span, { start: 100, end: 101 })).toEqual([
      { text: 'a', marked: true },
      { text: ' bounty of $500 here', marked: false },
    ])
  })
})

describe('lineOf', () => {
  it('counts from one', () => {
    expect(lineOf('a\nb\nc', 0)).toBe(1)
    expect(lineOf('a\nb\nc', 2)).toBe(2)
    expect(lineOf('a\nb\nc', 4)).toBe(3)
  })
})
