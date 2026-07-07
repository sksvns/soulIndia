import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { useAuth } from './AuthContext'

export function ProtectedRoute({ requirePermission }: { requirePermission?: string }) {
  const { user, loading, hasPermission } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', paddingTop: '20vh' }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  if (requirePermission && !hasPermission(requirePermission)) {
    return <Navigate to="/" replace />
  }

  return <Outlet />
}
