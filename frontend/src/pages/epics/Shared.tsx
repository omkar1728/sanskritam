import { Fragment } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import './epics.css'

export function Crumbs({ items }: { items: { label: string; to?: string }[] }) {
  return (
    <nav className="ep-crumbs" aria-label="Breadcrumb">
      {items.map((c, i) => (
        <Fragment key={i}>
          {i > 0 && <span className="sep">›</span>}
          {c.to ? <Link to={c.to}>{c.label}</Link> : <span>{c.label}</span>}
        </Fragment>
      ))}
    </nav>
  )
}

export const IMPORT_HINT = 'No data yet. Run the import: uv run python -m backend.app.epics_import'

export function Status({ loading, error, empty }: { loading: boolean; error: string; empty?: boolean }): ReactNode {
  if (loading) return <p className="muted">Loading…</p>
  if (error) return <p className="danger" role="alert">{error}</p>
  if (empty) return <p className="muted">{IMPORT_HINT}</p>
  return null
}
