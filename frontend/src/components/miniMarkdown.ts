import { createElement, Fragment, type ReactNode } from 'react'

// TERMS.mdの既知のmarkdown構文（#/##/### 見出し・|...|表1つ・-----区切り線・
// **太字**・[text](url)リンク・-箇条書き）だけを変換する軽量レンダラ。画像・コード
// ブロック・ネストしたリストは無い（実ファイルを確認して確定した構文サブセット）。
// 一般的なmarkdownライブラリ導入は、この1ファイルのためだけには過剰と判断し見送った
// （2026-08-23、frontend/package.jsonはreact/react-dom以外に依存を持たない）。

// 行内要素（太字・リンク）をReactNode配列に変換する
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let rest = text
  let i = 0
  // **bold** と [text](url) を順に検出。どちらにもマッチしなければ残りをそのまま出力。
  const pattern = /\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)/
  while (rest.length > 0) {
    const m = pattern.exec(rest)
    if (!m) {
      nodes.push(rest)
      break
    }
    if (m.index > 0) nodes.push(rest.slice(0, m.index))
    if (m[1] !== undefined) {
      nodes.push(createElement('strong', { key: `${keyPrefix}-${i++}` }, m[1]))
    } else {
      nodes.push(
        createElement('a', { key: `${keyPrefix}-${i++}`, href: m[3], target: '_blank', rel: 'noreferrer' }, m[2])
      )
    }
    rest = rest.slice(m.index + m[0].length)
  }
  return nodes
}

export function renderTermsMarkdown(source: string): ReactNode {
  const lines = source.split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]

    if (/^-{3,}\s*$/.test(line)) {
      blocks.push(createElement('hr', { key: key++ }))
      i++
      continue
    }

    const heading = /^(#{1,3})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      const tag = `h${level}`
      blocks.push(createElement(tag, { key: key++ }, renderInline(heading[2], `h${key}`)))
      i++
      continue
    }

    // 表: 連続する `|...|` 行をまとめて1つの<table>にする
    if (line.trim().startsWith('|')) {
      const tableLines: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i])
        i++
      }
      const rows = tableLines
        .filter(l => !/^\|[\s-:|]+\|$/.test(l.trim()))  // ヘッダー区切り行(|---|---|)を除外
        .map(l => l.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim()))
      if (rows.length > 0) {
        const [headerRow, ...bodyRows] = rows
        blocks.push(
          createElement(
            'table',
            { key: key++ },
            createElement(
              'thead',
              null,
              createElement(
                'tr',
                null,
                ...headerRow.map((c, ci) => createElement('th', { key: ci }, renderInline(c, `th${key}-${ci}`)))
              )
            ),
            createElement(
              'tbody',
              null,
              ...bodyRows.map((r, ri) =>
                createElement(
                  'tr',
                  { key: ri },
                  ...r.map((c, ci) => createElement('td', { key: ci }, renderInline(c, `td${key}-${ri}-${ci}`)))
                )
              )
            )
          )
        )
      }
      continue
    }

    // 箇条書き: 連続する `- ` 行をまとめて1つの<ul>にする
    if (/^-\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^-\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^-\s+/, ''))
        i++
      }
      blocks.push(
        createElement(
          'ul',
          { key: key++ },
          ...items.map((it, ii) => createElement('li', { key: ii }, renderInline(it, `li${key}-${ii}`)))
        )
      )
      continue
    }

    if (line.trim() === '') {
      i++
      continue
    }

    if (line.startsWith('> ')) {
      blocks.push(createElement('blockquote', { key: key++ }, renderInline(line.slice(2), `bq${key}`)))
      i++
      continue
    }

    // 通常の段落
    blocks.push(createElement('p', { key: key++ }, renderInline(line, `p${key}`)))
    i++
  }

  return createElement(Fragment, null, ...blocks)
}
