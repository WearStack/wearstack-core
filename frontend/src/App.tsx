import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AdminPage } from '@/features/admin/AdminPage'
import { ChangePasswordPage } from '@/features/auth/ChangePasswordPage'
import { LoginPage } from '@/features/auth/LoginPage'
import { RequireAuth, RequirePermission } from '@/features/auth/RequireAuth'
import { SetupPage } from '@/features/auth/SetupPage'
import { AppLayout } from '@/pages/AppLayout'
import { PosPage } from '@/features/pos/PosPage'
import { ReportsPage } from '@/features/reports/ReportsPage'
import { SyncPage } from '@/features/sync/SyncPage'
import { CustomersPage } from '@/pages/CustomersPage'
import { OverviewPage } from '@/pages/OverviewPage'
import { PurchasesPage } from '@/pages/PurchasesPage'
import { InventoryPage } from '@/pages/InventoryPage'
import { ProductsPage } from '@/pages/ProductsPage'
import { RolesPage } from '@/pages/RolesPage'
import { StoresPage } from '@/pages/StoresPage'
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
      <Route path="/change-password" element={<ChangePasswordPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route index element={<OverviewPage />} />
          <Route
            path="reports"
            element={
              <RequirePermission permission="report:read">
                <ReportsPage />
              </RequirePermission>
            }
          />
          <Route
            path="pos"
            element={
              <RequirePermission permission="sale:create">
                <PosPage />
              </RequirePermission>
            }
          />
          <Route
            path="sync"
            element={
              <RequirePermission permission="sale:create">
                <SyncPage />
              </RequirePermission>
            }
          />
          <Route
            path="purchases"
            element={
              <RequirePermission permission="purchase:read">
                <PurchasesPage />
              </RequirePermission>
            }
          />
          <Route
            path="customers"
            element={
              <RequirePermission permission="customer:read">
                <CustomersPage />
              </RequirePermission>
            }
          />
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
            path="admin"
            element={
              <RequirePermission permission="user:read">
                <AdminPage />
              </RequirePermission>
            }
          />
          <Route path="users" element={<Navigate to="/admin" replace />} />
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
      {/* Anything else (including addresses that never existed, like /signup) goes home, which
          sends someone who is not signed in to the sign-in page. */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
