import { SOURCE_FILTERS } from './helpers'
import type { SourceKey } from './helpers'

interface Props {
  counts: Record<SourceKey, number>
  selected: SourceKey[]
  shown: number
  total: number
  onChange: (s: SourceKey[]) => void
}

export default function SourceFilter({ counts, selected, shown, total, onChange }: Props) {
  const toggle = (k: SourceKey) => onChange(selected.includes(k) ? selected.filter(x => x !== k) : [...selected, k])
  return (
    <div className="ep-filter">
      <fieldset>
        <legend>Show verses that have any of these sources</legend>
        {SOURCE_FILTERS.map(({ key, label }) => {
          const n = counts[key]
          return (
            <label key={key} className={n === 0 ? 'off' : undefined}>
              <input type="checkbox" checked={selected.includes(key)} disabled={n === 0} onChange={() => toggle(key)} />
              {label} {n}
            </label>
          )
        })}
      </fieldset>
      <div className="ep-filter-bar" role="status">
        <span>Showing {shown} of {total} verses</span>
        <button type="button" onClick={() => onChange([])} disabled={!selected.length}>Clear</button>
      </div>
    </div>
  )
}
