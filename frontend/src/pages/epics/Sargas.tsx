import { Link, useParams } from 'react-router-dom'
import { api } from '../../api'
import { chapterNo, countLabel, epicLabels, epicPath, layerBadge, parseNum, sargaPath } from './helpers'
import { Crumbs, Status } from './Shared'
import { useEpic, useLoad } from './useLoad'

export default function Sargas() {
  const p = useParams()
  const id = p.epic ?? 'ramayana'
  const k = parseNum(p.kanda)
  const lb = epicLabels(useEpic(id), id)
  const { data, error, loading } = useLoad(
    () => (k == null ? Promise.reject(new Error(`Invalid ${lb.book} number`)) : api.epicSargas(id, k)), [id, k])
  return (
    <>
      <Crumbs items={[{ label: 'Epics', to: '/epics' }, { label: lb.name, to: epicPath(id) }, { label: `${lb.book} ${k ?? '?'}` }]} />
      <h1>{lb.book} {k}{data ? ` · ${countLabel(data.length, lb.chapter)}` : ''}</h1>
      <Status loading={loading} error={error} empty={!!data && data.length === 0} />
      {data && data.length > 0 && (
        <div className="ep-list">
          {data.map(s => {
            const badge = layerBadge(s.layer, s.sarga)
            const title_hi = s.title_hi ?? s.title_sa
            return (
              <Link key={s.sarga} className="ep-row" to={sargaPath(k!, s.sarga, id)}>
                <span>
                  <span className="ep-num">{s.sarga === 0 ? '·' : chapterNo(s.sarga, s.adhyaya_display)}</span>
                  {title_hi && <span className="devanagari" style={{ fontSize: '1.1rem' }}>{title_hi}</span>}
                  {badge && <span className="ep-badge warn" style={{ marginLeft: '.5rem' }}>{badge}</span>}
                  {s.title_en && <div className="muted">{s.title_en}</div>}
                  {!title_hi && !s.title_en && !badge && <span className="muted">{lb.chapter} {chapterNo(s.sarga, s.adhyaya_display)}</span>}
                </span>
                <span className="muted">{s.verse_count} v.</span>
              </Link>
            )
          })}
        </div>
      )}
    </>
  )
}
