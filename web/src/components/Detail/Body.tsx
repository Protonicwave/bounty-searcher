import { Fragment, useMemo } from 'react'

import { highlight, parseMarkdown, type Block, type Span } from '@/lib/markdown'

/** The offsets the payout was read at, or null when it was read elsewhere. */
export interface Range {
  start: number
  end: number
}

interface SpanProps {
  span: Span
  range: Range | null
}

/**
 * One span, split around the payout if the payout is inside it.
 *
 * The figure is marked where the parser found it rather than searched for
 * again, because the same characters often appear more than once in a body and
 * only one of them is the one that was believed.
 */
function SpanView({ span, range }: SpanProps) {
  const pieces = highlight(span, range).map((piece, i) =>
    piece.marked ? (
      <mark
        key={i}
        className="border-b border-accent-rule bg-transparent pb-px text-accent"
      >
        {piece.text}
      </mark>
    ) : (
      <Fragment key={i}>{piece.text}</Fragment>
    ),
  )

  switch (span.kind) {
    case 'code':
      return (
        <code className="bg-line-soft px-[4px] py-px font-mono text-sm text-fg-dim">
          {pieces}
        </code>
      )
    case 'strong':
      return <strong className="font-semibold text-fg">{pieces}</strong>
    case 'em':
      return <em>{pieces}</em>
    case 'link':
      return (
        <a
          href={span.href}
          target="_blank"
          rel="noreferrer noopener"
          className="text-fg-dim underline underline-offset-2"
        >
          {pieces}
        </a>
      )
    default:
      return <>{pieces}</>
  }
}

function Spans({ spans, range }: { spans: Span[]; range: Range | null }) {
  return spans.map((span, i) => <SpanView key={i} span={span} range={range} />)
}

function BlockView({ block, range }: { block: Block; range: Range | null }) {
  switch (block.kind) {
    case 'heading':
      return (
        <p className="mt-[16px] mb-[8px] text-fg">
          <strong className="font-semibold">
            <Spans spans={block.spans} range={range} />
          </strong>
        </p>
      )
    case 'code':
      return (
        <pre className="scrollbar-thin mb-[11px] overflow-x-auto bg-line-soft p-[10px] font-mono text-sm text-fg-dim">
          {block.text}
        </pre>
      )
    case 'list':
      return block.ordered ? (
        <ol className="mb-[11px] list-decimal pl-[18px]">
          {block.items.map((item, i) => (
            <li key={i} className="mb-[4px]">
              <Spans spans={item} range={range} />
            </li>
          ))}
        </ol>
      ) : (
        <ul className="mb-[11px] list-disc pl-[18px]">
          {block.items.map((item, i) => (
            <li key={i} className="mb-[4px]">
              <Spans spans={item} range={range} />
            </li>
          ))}
        </ul>
      )
    case 'quote':
      return (
        <blockquote className="mb-[11px] border-l border-line pl-[10px] text-fg-dimmer">
          <Spans spans={block.spans} range={range} />
        </blockquote>
      )
    default:
      return (
        <p className="mb-[11px]">
          <Spans spans={block.spans} range={range} />
        </p>
      )
  }
}

/**
 * The issue, in the sans at a measure.
 *
 * Prose gets the humanist face and 62 characters to run in. Full-width body
 * copy is the loudest tell of an interface built without a typographer, and
 * the pane is forty per cent of the window for exactly this reason.
 */
export function Body({ source, range }: { source: string; range: Range | null }) {
  const blocks = useMemo(() => parseMarkdown(source), [source])
  if (blocks.length === 0) {
    return <p className="font-sans text-base text-fg-dimmer">No description.</p>
  }
  return (
    <div className="max-w-measure font-sans text-base leading-[1.62] text-prose">
      {blocks.map((block, i) => (
        <BlockView key={i} block={block} range={range} />
      ))}
    </div>
  )
}
