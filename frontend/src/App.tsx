import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './layout/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'
import { ComingSoonPage } from './pages/ComingSoonPage'

function App() {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#aa3bff' } }}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                <Route index element={<DashboardPage />} />
                <Route path="stores" element={<ComingSoonPage title="Store-wise view" />} />
                <Route
                  path="categories"
                  element={<ComingSoonPage title="Category-wise view" />}
                />
                <Route path="trends" element={<ComingSoonPage title="Trends view" />} />
                <Route path="upload" element={<ComingSoonPage title="Upload" />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
