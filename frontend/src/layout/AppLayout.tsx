import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, Avatar, Dropdown, Typography, theme } from 'antd'
import {
  DashboardOutlined,
  ShopOutlined,
  AppstoreOutlined,
  LineChartOutlined,
  UploadOutlined,
  DeleteOutlined,
  UserOutlined,
  LogoutOutlined,
} from '@ant-design/icons'
import { useAuth } from '../auth/AuthContext'
import { FilterProvider } from '../filters/FilterContext'
import { FilterBar } from '../filters/FilterBar'
import { OperationsProvider } from '../operations/OperationsContext'

const { Header, Sider, Content } = Layout

// Subcategory/Color/Size/Fit read as children of Categories (client
// feedback) -- a flat, always-visible list with a slight indent, not a
// collapsible AntD submenu (no click-to-expand needed).
const childLabel = (text: string) => <span style={{ paddingLeft: 24 }}>{text}</span>

const NAV_ITEMS = [
  { key: '/', icon: <DashboardOutlined />, label: 'Dashboard' },
  { key: '/stores', icon: <ShopOutlined />, label: 'Stores' },
  { key: '/categories', icon: <AppstoreOutlined />, label: 'Categories' },
  { key: '/subcategories', label: childLabel('Subcategory') },
  { key: '/colors', label: childLabel('Color') },
  { key: '/sizes', label: childLabel('Size') },
  { key: '/fits', label: childLabel('Fit') },
  { key: '/trends', icon: <LineChartOutlined />, label: 'Trends' },
  { key: '/upload', icon: <UploadOutlined />, label: 'Upload' },
  { key: '/delete-data', icon: <DeleteOutlined />, label: 'Delete Data' },
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
    <OperationsProvider>
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
            {![
              '/upload',
              '/delete-data',
              '/',
              '/stores',
              '/categories',
              '/subcategories',
              '/colors',
              '/sizes',
              '/fits',
            ].includes(location.pathname) && <FilterBar />}
            <Content style={{ margin: 16 }}>
              <Outlet />
            </Content>
          </Layout>
        </Layout>
      </FilterProvider>
    </OperationsProvider>
  )
}
