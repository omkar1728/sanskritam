import { Link } from 'react-router-dom'
import { api } from '../../api'
import { countLabel } from './helpers'
import { Crumbs, Status } from './Shared'
import { useLoad } from './useLoad'

export default function EpicsHome() {
  const { data, error, loading } = useLoad(() => api.epics(), [])
  return (
    <>
      <Crumbs items={[{ label: 'Epics' }]} />
      <h1>Epics</h1>
      <Status loading={loading} error={error} empty={!!data && data.length === 0} />
      <div className="ep-grid">
        {data?.map(e => (
          <Link key={e.id} className="card" to={`/epics/${e.id}`}>
            <h2>{e.name}</h2>
            {e.name_sa && <div className="devanagari">{e.name_sa}</div>}
            <div className="muted">{countLabel(e.kanda_count, e.book_label || 'Kāṇḍa')} · {e.verse_count} verses</div>
          </Link>
        ))}
      </div>
    </>
  )
}
