import { useEffect } from 'react'
import { Route, Routes } from 'react-router-dom'
import { LoginPage } from '@/features/auth/LoginPage'
import { RequireAuth, RequirePermission } from '@/features/auth/RequireAuth'
import { SetupPage } from '@/features/auth/SetupPage'
import { AppLayout } from '@/pages/AppLayout'
import { HomePage } from '@/pages/HomePage'
import { InventoryPage } from '@/pages/InventoryPage'
import { ProductsPage } from '@/pages/ProductsPage'
import { RolesPage } from '@/pages/RolesPage'
import { StoresPage } from '@/pages/StoresPage'
import { UsersPage } from '@/pages/UsersPage'
import { useAuthStore } from '@/stores/auth'

export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap)
  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/setup" element={<SetupPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route index element={<HomePage />} />
          <Route
            path="products"
            element={
              <RequirePermission permission="product:read">
                <ProductsPage />
              </RequirePermission>
            }
          />
          <Route
            path="inventory"
            element={
              <RequirePermission permission="inventory:read">
                <InventoryPage />
              </RequirePermission>
            }
          />
          <Route
            path="stores"
            element={
              <RequirePermission permission="store:read">
                <StoresPage />
              </RequirePermission>
            }
          />
          <Route
            path="users"
            element={
              <RequirePermission permission="user:read">
                <UsersPage />
              </RequirePermission>
            }
          />
          <Route
            path="roles"
            element={
              <RequirePermission permission="role:read">
                <RolesPage />
              </RequirePermission>
            }
          />
        </Route>
      </Route>
    </Routes>
  )
}
