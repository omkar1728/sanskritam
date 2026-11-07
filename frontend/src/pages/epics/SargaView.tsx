import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api'
import type {
  AudioRef, CriticalNote, EpicAlignmentRow, EpicMeaningItem, EpicSupplement, EpicVerse, SargaDetail,
} from '../../types'
import {
  VARIANTS, availableVariants, chapterTitle, epicLabels, epicPath, isUnverified, isVariantKey, kandaPath,
  layerBadge, loadVariantPref, looseText, parseNum, pickVariant, refLabel, saveVariantPref, sargaPath, unitLabel,
  variantLines, variantSource, verseKindBadge, loadSourceSel, saveSourceSel, sourceCounts, filterBySources,
} from './helpers'
import type { SourceKey, VariantKey } from './helpers'
import InlineChant from './InlineChant'
import SourceFilter from './SourceFilter'
import { Crumbs, Status } from './Shared'
import { useEpic, useLoad } from './useLoad'

/** Renders children only once the <details> has been opened (keeps long sargas fast). */
function Lazy({ summary, children }: { summary: string; children: () => ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <details onToggle={e => { if ((e.currentTarget as HTMLDetailsElement).open) setOpen(true) }}>
      <summary>{summary}</summary>
      {open && children()}
    </details>
  )
}

function Src({ m, review }: { m: EpicMeaningItem; review: string }) {
  return (
    <div className="ep-src">
      <span>Source: {unitLabel(m)}</span>
      <span className="ep-badge warn">{review}</span>
      {isUnverified(m) && <span className="ep-badge warn">unverified</span>}
      {m.spans_beyond_this_verse && <span className="ep-badge">spans beyond this verse</span>}
      {m.provenance && <span>{m.provenance}</span>}
      {m.rights && <span>Rights: {m.rights}</span>}
      {m.licence_note && <span>Licence: {m.licence_note}</span>}
      {m.ref && <span>Ref: {m.ref}</span>}
    </div>
  )
}

function Items({ items, review, kind }: { items: EpicMeaningItem[] | null | undefined; review: string; kind: 'text' | 'words' }) {
  if (!items || !items.length) return <p className="muted">None available.</p>
  return (
    <>
      {items.map((m, i) => (
        <div className="ep-item" key={i}>
          {kind === 'text' && <p className="ep-pre" lang="en">{m.text}</p>}
          {kind === 'words' && m.words && (
            <div className="ep-table-wrap">
              <table className="ep-table">
                <thead>
                  <tr>
                    {m.words.some(w => w.roman_itrans) ? (
                      <><th>ITRANS</th><th>Devanagari (machine-converted)</th><th>English</th></>
                    ) : (
                      <><th>Sanskrit</th><th>Hindi</th></>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {m.words.map((w, j) => w.roman_itrans !== undefined || w.devanagari_machine_converted !== undefined ? (
                    <tr key={j}><td>{w.roman_itrans}</td><td className="devanagari" style={{ fontSize: '1.1rem' }}>{w.devanagari_machine_converted}</td><td>{w.english}</td></tr>
                  ) : (
                    <tr key={j}><td className="devanagari" style={{ fontSize: '1.1rem' }}>{w.sanskrit}</td><td>{w.hindi}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Src m={m} review={review} />
          {m.note && <div className="ep-src">{m.note}</div>}
        </div>
      ))}
    </>
  )
}

const count = (a: unknown[] | null | undefined) => (a && a.length ? ` (${a.length})` : '')

function Alignment({ rows }: { rows: EpicAlignmentRow[] }) {
  return (
    <>
      {rows.map((r, i) => (
        <div className="ep-item" key={i}>
          <div className="ep-src">
            <span>Row {i + 1}</span>
            {r.confidence && <span className={`ep-badge${r.confidence === 'high' ? '' : ' warn'}`}>confidence: {r.confidence}</span>}
            {r.similarity && Object.entries(r.similarity).map(([k, v]) => <span key={k}>{k}: {Number(v).toFixed(2)}</span>)}
          </div>
          {([['smith', 'Critical'], ['net', 'net'], ['in', '.in'], ['gp', 'Gita Press']] as const).map(([k, l]) =>
            r[k] ? <div key={k}><span className="muted">{l}: </span><span className="devanagari" style={{ fontSize: '1.1rem' }}>{r[k]}</span></div> : null)}
          {r.word_diffs && Object.entries(r.word_diffs).map(([k, d]) => (
            <div key={k} className="ep-src">
              <span>{k}:</span>
              {d.map((x, j) => <span key={j} className="devanagari" style={{ fontSize: '1rem' }}>{x.a || '∅'} → {x.b || '∅'}</span>)}
            </div>
          ))}
        </div>
      ))}
    </>
  )
}

function Variants({ v }: { v: EpicVerse }) {
  return (
    <>
      {VARIANTS.map(({ key, label }) => {
        const lines = variantLines(v, key)
        return (
          <div className="ep-item" key={key}>
            <strong>{label}</strong>{key === 'critical' && <span className="muted"> (derived punctuation)</span>}
            {lines ? <div className="devanagari" style={{ fontSize: '1.15rem', whiteSpace: 'pre-wrap' }}>{lines.join('\n')}</div> : <p className="muted">Not available.</p>}
            {lines && <div className="ep-src">Source: {variantSource(v, key) ?? 'unknown'}{key === 'gitapress' && ' (OCR, unverified)'}</div>}
          </div>
        )
      })}
    </>
  )
}

function Supplements({ items }: { items: (EpicSupplement | string)[] }) {
  return (
    <>
      {items.map((x, i) => typeof x === 'string' ? <p key={i} className="ep-pre">{x}</p> : (
        <div className="ep-item" key={i}>
          <div className="ep-src">
            {x.passage_id && <span>{x.passage_id}</span>}
            {x.kind && <span className="ep-badge">{x.kind.replace(/_/g, ' ')}</span>}
            {x.placement && <span>{x.placement.replace(/_/g, ' ')}</span>}
          </div>
          {x.apparatus?.length ? <div className="ep-src">{x.apparatus.join(' ')}</div> : null}
          <div className="devanagari" style={{ fontSize: '1.1rem', whiteSpace: 'pre-wrap' }}>
            {(x.lines ?? []).map(l => (typeof l === 'string' ? l : l.text ?? '')).join('\n')}
          </div>
        </div>
      ))}
    </>
  )
}

function Loose({ items }: { items: unknown[] }) {
  return <>{items.map((x, i) => <p key={i} className="ep-pre ep-item">{looseText(x)}</p>)}</>
}

function Notes({ notes }: { notes: (CriticalNote | string)[] }) {
  return (
    <>
      {notes.map((n, i) => typeof n === 'string' ? <p key={i} className="ep-pre">{n}</p> : (
        <div className="ep-item" key={i}>
          {n.comment && <p className="ep-pre">{n.comment}</p>}
          {n.star_passages?.map((s, j) => (
            <div key={j}><strong>{s.label}</strong><div className="devanagari" style={{ fontSize: '1.1rem', whiteSpace: 'pre-wrap' }}>{s.lines?.join('\n')}</div></div>
          ))}
        </div>
      ))}
    </>
  )
}

const fmtDur = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

function VerseCard({ v, pref, audio, epic }: { v: EpicVerse; pref: string | null; audio?: AudioRef[]; epic: string }) {
  const key = pickVariant(v, pref)
  const lines = key ? variantLines(v, key) : null
  const southern = variantLines(v, 'southern')
  const iast = variantLines(v, 'iast')
  const m = v.meanings ?? {}
  const review = v.review_status ?? 'unreviewed'
  const hindi = [...(m.hindi_translation ?? []), ...(m.hindi_translation_gitapress ?? [])]
  const known = ['translation_unit_refs', 'english_translation', 'english_word_by_word', 'english_commentary', 'hindi_translation', 'hindi_word_by_word', 'hindi_translation_gitapress']
  const other = Object.entries(m).filter(([k, x]) => !known.includes(k) && x && x.length)
  return (
    <article className="card ep-verse" id={`v-${v.seq_in_sarga ?? v.id}`}>
      <div className="ep-ref">
        <strong>{refLabel(v)}</strong>
        {verseKindBadge(v.kind) && <span className="ep-badge">{verseKindBadge(v.kind)}</span>}
        <span className="ep-badge warn">{review}</span>
        {key && <span className="ep-badge">{VARIANTS.find(x => x.key === key)?.label}{key === 'critical' ? ' · derived punctuation' : ''}{key === 'gitapress' ? ' · OCR, unverified' : ''}</span>}
      </div>
      <div className="ep-text" hidden={!!audio?.length}>
        {lines ? <div className={key === 'iast' || key === 'raw' ? 'ep-pre' : 'devanagari'} lang="sa">{lines.join('\n')}</div> : <p className="muted">No text available.</p>}
        {key === 'hv_deva' && <div className="ep-src"><span className="ep-badge warn">machine transliteration</span><span>{variantSource(v, 'hv_deva')}</span></div>}
        {key === 'passage' && v.passage && (
          <div className="ep-src">
            {v.passage.passage_id && <span>{v.passage.passage_id}</span>}
            {v.passage.kind && <span className="ep-badge">{v.passage.kind.replace(/_/g, ' ')}</span>}
            {v.passage.placement && <span>{v.passage.placement.replace(/_/g, ' ')}</span>}
            {v.passage.apparatus?.map((a, i) => <span key={i}>{a}</span>)}
          </div>
        )}
      </div>
      {audio && (
        <div className="ep-audio">
          <strong>Audio</strong>
          {audio.length > 0 ? (
            <>
              <div className="ep-src">
                <span>{audio[0].meter_id} · {audio[0].voice_id} · {audio[0].steps} steps · {fmtDur(audio[0].duration)}</span>
                <Link to={`/learn/${audio[0].job_id}`}>Open full page</Link>
              </div>
              <InlineChant verseId={`${epic}-${v.id}`} audio={audio[0]} />
              {audio.slice(1).map(a => (
                <div className="ep-src" key={a.job_id}>
                  <Link to={`/learn/${a.job_id}`}>▶ {a.meter_id} · {a.voice_id} · {a.steps} steps · {fmtDur(a.duration)}</Link>
                </div>
              ))}
            </>
          ) : <span className="muted"> No audio yet.</span>}
        </div>
      )}
      {iast && key !== 'iast' && (
        <div className="ep-item">
          <div className="ep-src"><span className="ep-badge">IAST original</span><span>{variantSource(v, 'iast')}</span></div>
          <div className="ep-pre" lang="sa">{iast.join('\n')}</div>
        </div>
      )}
      {southern && key !== 'southern' && (
        <div className="ep-item">
          <div className="ep-src"><span className="ep-badge">Southern recension</span><span>{variantSource(v, 'southern') ?? 'SARIT'}</span></div>
          <div className="devanagari" lang="sa" style={{ fontSize: '1.15rem', whiteSpace: 'pre-wrap' }}>{southern.join('\n')}</div>
        </div>
      )}
      {m.english_translation?.length && m.english_translation[0].text ? (
        <>
          <p lang="en">{m.english_translation[0].text}</p>
          <div className="ep-src"><span>Source: {unitLabel(m.english_translation[0])}</span></div>
        </>
      ) : null}
      <Lazy summary={`English translation${count(m.english_translation)}`}>{() => <Items items={m.english_translation} review={review} kind="text" />}</Lazy>
      <Lazy summary={`Word by word${count(m.english_word_by_word)}`}>{() => (
        <>
          <Items items={m.english_word_by_word} review={review} kind="words" />
          {m.hindi_word_by_word?.length ? <><h4>Hindi word table (unverified, looks machine-generated)</h4><Items items={m.hindi_word_by_word} review={review} kind="words" /></> : null}
        </>
      )}</Lazy>
      <Lazy summary={`Hindi translation${count(hindi)}`}>{() => <Items items={hindi} review={review} kind="text" />}</Lazy>
      <Lazy summary={`Commentary${count(m.english_commentary)}`}>{() => <Items items={m.english_commentary} review={review} kind="text" />}</Lazy>
      {other.map(([k, items]) => <Lazy key={k} summary={k.replace(/_/g, ' ')}>{() => <Items items={items} review={review} kind="text" />}</Lazy>)}
      <Lazy summary={`Supplements${count(v.supplements)}`}>{() => v.supplements?.length ? <Supplements items={v.supplements} /> : <p className="muted">None.</p>}</Lazy>
      <Lazy summary="All text variants">{() => <Variants v={v} />}</Lazy>
      <Lazy summary={`Alignment${count(v.alignment)}`}>{() => v.alignment?.length ? <Alignment rows={v.alignment} /> : <p className="muted">None.</p>}</Lazy>
      <Lazy summary={`Critical edition notes${count(v.critical_edition_notes)}`}>{() => v.critical_edition_notes?.length ? <Notes notes={v.critical_edition_notes} /> : <p className="muted">None.</p>}</Lazy>
      <Lazy summary={`Flags${count(v.flags)}`}>{() => v.flags?.length ? <ul>{v.flags.map(f => <li key={f}>{f}</li>)}</ul> : <p className="muted">None.</p>}</Lazy>
    </article>
  )
}

function Pager({ d, k, epic, chapter }: { d: SargaDetail; k: number; epic: string; chapter: string }) {
  return (
    <div className="ep-pager">
      {d.prev ? <Link to={sargaPath(k, d.prev.sarga, epic)}>← {chapterTitle(chapter, d.prev.sarga, d.prev.adhyaya_display, null, true)}</Link> : <span />}
      {d.next ? <Link to={sargaPath(k, d.next.sarga, epic)}>{chapterTitle(chapter, d.next.sarga, d.next.adhyaya_display, null, true)} →</Link> : <span />}
    </div>
  )
}

export default function SargaView() {
  const p = useParams()
  const id = p.epic ?? 'ramayana'
  const lb = epicLabels(useEpic(id), id)
  const k = parseNum(p.kanda), s = parseNum(p.sarga)
  const [pref, setPref] = useState<string | null>(() => loadVariantPref())
  const { data, error, loading } = useLoad(
    () => (k == null || s == null ? Promise.reject(new Error(`Invalid ${lb.book} or ${lb.chapter}`)) : api.epicSarga(id, k, s)), [id, k, s])
  // chants rendered for this chapter's verses (library verse id = `${epic}-${verse id}`); none when the list can't load
  const { data: lib } = useLoad(() => api.verses().catch(() => []), [])
  const chants = useMemo(() => {
    const m = new Map<string, AudioRef[]>()
    for (const x of lib ?? []) m.set(x.id, x.audio ?? [])
    return m
  }, [lib])
  const [srcSel, setSrcSel] = useState<SourceKey[]>(() => loadSourceSel())
  const chooseSrc = (x: SourceKey[]) => { setSrcSel(x); saveSourceSel(x) }
  const choose = (key: VariantKey) => { setPref(key); saveVariantPref(key) }
  const meta = data?.meta
  const titleHi = meta?.title_hi_from_in, titleEn = meta?.title_en_from_in, intro = meta?.intro_en_from_net
  const kName = data?.kanda.name_en ?? `${lb.book} ${k}`
  const disp = data?.verses.find(v => v.adhyaya_display != null)?.adhyaya_display
  const heading = data ? chapterTitle(lb.chapter, data.sarga, disp, data.layer) : `${lb.chapter} ${s ?? '?'}`
  const badge = data ? layerBadge(data.layer, data.sarga) : null
  const licence = meta?.licence_note ?? data?.verses.find(v => v.licence_note)?.licence_note
  const chMeanings = meta?.meanings?.english_translation
  const sc = meta?.southern_chapters?.filter(c => c.head || c.topic)
  const unplacedT = meta?.translations_unplaced_verse ?? [], unplacedS = meta?.supplements_unplaced_verse ?? []
  const present = data ? VARIANTS.filter(x => data.verses.some(v => availableVariants(v).includes(x.key))) : VARIANTS
  const filterable = id !== 'ramayana'
  const counts = useMemo(() => sourceCounts(data?.verses ?? []), [data])
  // Only ticked options that exist in this chapter apply, so a stale remembered tick cannot hide everything.
  const activeSel = filterable ? srcSel.filter(k => counts[k] > 0) : []
  const shownVerses = data ? filterBySources(data.verses, activeSel) : []
  const showBar = filterable && !!data && data.verses.length > 0 && Object.values(counts).some(n => n > 0)
  return (
    <>
      <Crumbs items={[
        { label: 'Epics', to: '/epics' }, { label: lb.name, to: epicPath(id) },
        { label: kName, to: k != null ? kandaPath(k, id) : undefined }, { label: data ? chapterTitle(lb.chapter, data.sarga, disp, data.layer, true) : heading },
      ]} />
      <Status loading={loading} error={error} empty={!!data && data.verses.length === 0} />
      {data && k != null && (
        <>
          <h1>{kName} · {heading}{badge && data.sarga !== 0 ? <span className="ep-badge warn" style={{ marginLeft: '.6rem' }}>{badge}</span> : null}</h1>
          {titleHi && <div className="devanagari" style={{ fontSize: '1.2rem' }}>{titleHi}</div>}
          {titleEn && <h2>{titleEn}</h2>}
          {(titleHi || titleEn) && <p className="muted">Titles from valmikiramayan.in (unreviewed).</p>}
          {intro && <details><summary>Introduction (English, from valmikiramayan.net)</summary><p className="ep-intro">{intro}</p></details>}
          {licence && <p className="ep-notice" role="note">{licence}</p>}
          {meta?.review_status && <p className="muted">Chapter review status: <span className="ep-badge warn">{meta.review_status}</span></p>}
          {sc && sc.length > 0 && (
            <Lazy summary="Southern chapter heading and topic">{() => sc.map((c, i) => (
              <div className="ep-item" key={i}>
                {c.head && <strong className="devanagari" style={{ fontSize: '1.1rem' }}>{c.head}</strong>}
                {c.topic && <div className="devanagari" style={{ fontSize: '1rem' }}>{c.topic}</div>}
              </div>
            ))}</Lazy>
          )}
          {chMeanings && chMeanings.length > 0 && (
            <Lazy summary={`Chapter-level English: ${[...new Set(chMeanings.map(c => c.source).filter(Boolean))].join('; ') || 'source unknown'} (long)${count(chMeanings)}`}>{() => (
              <Items items={chMeanings} review={meta?.review_status ?? 'unreviewed'} kind="text" />
            )}</Lazy>
          )}
          {(unplacedT.length > 0 || unplacedS.length > 0) && (
            <Lazy summary={`Unplaced translations (${unplacedT.length}) and supplements (${unplacedS.length})`}>{() => (
              <>
                {unplacedT.length > 0 && <><h4>Unplaced translations (unverified)</h4><Loose items={unplacedT} /></>}
                {unplacedS.length > 0 && <><h4>Unplaced supplements</h4><Loose items={unplacedS} /></>}
              </>
            )}</Lazy>
          )}
          <Pager d={data} k={k} epic={id} chapter={lb.chapter} />
          {data.verses.length > 0 && (
            <div className="ep-toggle" role="group" aria-label="Text variant">
              {present.map(x => (
                <button key={x.key} className={pref === x.key || (!isVariantKey(pref) && x.key === 'critical') ? 'on' : ''} onClick={() => choose(x.key)}>{x.label}</button>
              ))}
            </div>
          )}
          {showBar && <SourceFilter counts={counts} selected={activeSel} shown={shownVerses.length} total={data.verses.length} onChange={chooseSrc} />}
          {data.verses.length > 0 && shownVerses.length === 0 && <p className="muted" role="status">No verses in this chapter match the selected sources. Use Clear to show all.</p>}
          {shownVerses.map(v => <VerseCard key={v.id} v={v} pref={pref} epic={id} audio={lib ? (chants.get(`${id}-${v.id}`) ?? []) : undefined} />)}
          <Pager d={data} k={k} epic={id} chapter={lb.chapter} />
        </>
      )}
    </>
  )
}
