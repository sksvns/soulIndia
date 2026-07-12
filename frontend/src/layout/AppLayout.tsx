import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, Avatar, Dropdown, Typography, theme } from 'antd'
import {
  DashboardOutlined,
  ShopOutlined,
  AppstoreOutlined,
  LineChartOutlined,
  UploadOutlined,
  UserOutlined,
  LogoutOutlined,
} from '@ant-design/icons'
import { useAuth } from '../auth/AuthContext'
import { FilterProvider } from '../filters/FilterContext'
import { FilterBar } from '../filters/FilterBar'

const { Header, Sider, Content } = Layout

const NAV_ITEMS = [
  { key: '/', icon: <DashboardOutlined />, label: 'Dashboard' },
  { key: '/stores', icon: <ShopOutlined />, label: 'Stores' },
  { key: '/categories', icon: <AppstoreOutlined />, label: 'Categories' },
  { key: '/trends', icon: <LineChartOutlined />, label: 'Trends' },
  { key: '/upload', icon: <UploadOutlined />, label: 'Upload' },
]

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const {
    token: { colorBgContainer },
  } = theme.useToken()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <FilterProvider>
      <Layout style={{ minHeight: '100vh' }}>
        <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}>
          <div
            style={{
              height: 48,
              margin: 12,
              color: 'white',
              fontWeight: 600,
              fontSize: collapsed ? 14 : 16,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
            }}
          >
            {collapsed ? 'SI' : 'Soul India'}
          </div>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[location.pathname]}
            items={NAV_ITEMS}
            onClick={({ key }) => navigate(key)}
          />
        </Sider>
        <Layout>
          <Header
            style={{
              background: colorBgContainer,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
              gap: 16,
              paddingInline: 24,
            }}
          >
            <Dropdown
              menu={{
                items: [{ key: 'logout', icon: <LogoutOutlined />, label: 'Log out' }],
                onClick: handleLogout,
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <Avatar icon={<UserOutlined />} size="small" />
                <Typography.Text>{user?.email}</Typography.Text>
              </span>
            </Dropdown>
          </Header>
          {location.pathname !== '/upload' && location.pathname !== '/' && <FilterBar />}
          <Content style={{ margin: 16 }}>
            <Outlet />
          </Content>
        </Layout>
      </Layout>
    </FilterProvider>
  )
}
