import { NavLink, Route, Routes } from 'react-router-dom'
import Library from './pages/Library'
import Generate from './pages/Generate'
import Learn from './pages/Learn'
import Settings from './pages/Settings'

export default function App() {
  return (
    <>
      <nav className="app-nav">
        <span className="brand">Sanskrit Śloka Studio</span>
        <NavLink to="/library">Library</NavLink>
        <NavLink to="/generate">Generate</NavLink>
        <NavLink to="/settings">Settings</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/library" element={<Library />} />
          <Route path="/generate" element={<Generate />} />
          <Route path="/learn/:jobId" element={<Learn />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </>
  )
}
