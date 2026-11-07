import { Link, useParams } from 'react-router-dom'
import { api } from '../../api'
import { countLabel, epicLabels, kandaPath } from './helpers'
import { Crumbs, Status } from './Shared'
import { useEpic, useLoad } from './useLoad'

export default function Kandas() {
  const id = useParams().epic ?? 'ramayana'
  const lb = epicLabels(useEpic(id), id)
  const { data, error, loading } = useLoad(() => api.epicKandas(id), [id])
  return (
    <>
      <Crumbs items={[{ label: 'Epics', to: '/epics' }, { label: lb.name }]} />
      <h1>{lb.name}</h1>
      <Status loading={loading} error={error} empty={!!data && data.length === 0} />
      <div className="ep-grid">
        {data?.map(k => (
          <Link key={k.number} className="card" to={kandaPath(k.number, id)}>
            <h2><span className="ep-num">{k.number}</span>{k.name_en ?? `${lb.book} ${k.number}`}</h2>
            {k.name_sa && <div className="devanagari">{k.name_sa}</div>}
            <div className="muted">{countLabel(k.sarga_count, lb.chapter)} · {k.verse_count} verses</div>
          </Link>
        ))}
      </div>
    </>
  )
}
