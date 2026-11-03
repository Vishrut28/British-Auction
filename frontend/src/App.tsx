import { Link, NavLink, Route, Routes } from 'react-router-dom'
import { CreateRfqPage } from './pages/CreateRfqPage'
import { RfqDetailPage } from './pages/RfqDetailPage'
import { RfqListPage } from './pages/RfqListPage'

export default function App() {
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand">
            British Auction RFQ
          </Link>
          <nav>
            <NavLink to="/" end>
              Auctions
            </NavLink>
            <NavLink to="/rfqs/new" className="btn btn-primary btn-sm">
              New RFQ
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="page">
        <Routes>
          <Route path="/" element={<RfqListPage />} />
          <Route path="/rfqs/new" element={<CreateRfqPage />} />
          <Route path="/rfqs/:id" element={<RfqDetailPage />} />
          <Route path="*" element={<p className="muted">Page not found.</p>} />
        </Routes>
      </main>
    </>
  )
}
