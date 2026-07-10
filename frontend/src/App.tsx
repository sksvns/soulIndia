import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './layout/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'
import { StoresPage } from './pages/StoresPage'
import { CategoriesPage } from './pages/CategoriesPage'
import { TrendsPage } from './pages/TrendsPage'
import { UploadPage } from './pages/UploadPage'

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
                <Route path="stores" element={<StoresPage />} />
                <Route path="categories" element={<CategoriesPage />} />
                <Route path="trends" element={<TrendsPage />} />
                <Route path="upload" element={<UploadPage />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
