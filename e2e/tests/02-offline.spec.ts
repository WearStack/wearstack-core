import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test'

/**
 * Offline selling, end to end, in a real browser that really goes offline.
 *
 * Runs after 01-retail-flow (it reuses the shop that spec built: the owner, a cashier, and the
 * "Classic Cotton Shirt" product with its M and L variants). Each browser context is a separate
 * device with its own IndexedDB, exactly like two tills in a shop.
 */
const PROD = !!process.env.E2E_PROD
const API = process.env.API_URL ?? (PROD ? 'http://localhost:8081/api' : 'http://localhost:8010')
const OWNER = { email: 'demo@example.com', password: 'demo-password-1' }
const CASHIER = { email: 'cashier@example.com', password: 'cashier-password-2' }

async function token(browser: Browser, who: { email: string; password: string }): Promise<string> {
  const ctx = await browser.newContext()
  const res = await ctx.request.post(`${API}/auth/login`, { data: who })
  const t = (await res.json()).access_token as string
  await ctx.close()
  return t
}

/** A small API helper for arranging stock; the behaviour under test goes through the UI. */
async function arrangeStock(browser: Browser, sku: RegExp, quantity: number): Promise<string> {
  const ctx = await browser.newContext()
  const headers = { Authorization: `Bearer ${await token(browser, OWNER)}` }
  const stores = await (await ctx.request.get(`${API}/stores`, { headers })).json()
  const rows = await (await ctx.request.get(`${API}/inventory?store_id=${stores[0].id}`, { headers })).json()
  const row = rows.find((r: { sku: string }) => sku.test(r.sku))
  const delta = quantity - row.quantity
  if (delta !== 0) {
    const res = await ctx.request.post(`${API}/inventory/movements`, {
      headers,
      data: { store_id: stores[0].id, variant_id: row.variant_id, kind: 'adjustment', quantity: delta, reason: 'Test setup' },
    })
    expect(res.ok()).toBeTruthy()
  }
  await ctx.close()
  return row.variant_id as string
}

async function serverStock(browser: Browser, sku: RegExp): Promise<number> {
  const ctx = await browser.newContext()
  const headers = { Authorization: `Bearer ${await token(browser, OWNER)}` }
  const stores = await (await ctx.request.get(`${API}/stores`, { headers })).json()
  const rows = await (await ctx.request.get(`${API}/inventory?store_id=${stores[0].id}`, { headers })).json()
  await ctx.close()
  return rows.find((r: { sku: string }) => sku.test(r.sku)).quantity as number
}

async function signIn(page: Page, who: { email: string; password: string }) {
  await page.goto('/login')
  await page.getByLabel('Email address').fill(who.email)
  await page.getByLabel('Password').fill(who.password)
  await page.getByLabel('Remember me').check()
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
}

const nav = (page: Page, name: string) => page.getByRole('link', { name, exact: true }).click()
const badge = (page: Page) => page.getByRole('link', { name: 'Sync status' })

/** Opens the Sync page and waits until this device has downloaded the catalogue. */
async function waitForCatalogue(page: Page) {
  await nav(page, 'Sync')
  await expect(page.getByRole('main').getByText('CATALOGUE', { exact: true }).locator('xpath=..')).toContainText('h old', {
    timeout: 15_000,
  })
}

async function addMToCart(page: Page, times = 1) {
  const search = page.getByPlaceholder('Scan barcode or search name / SKU…')
  await search.fill('Classic')
  const row = page.getByRole('listitem').filter({ hasText: 'CLA-M-' })
  for (let i = 0; i < times; i++) await row.getByRole('button', { name: 'Add' }).click()
}

async function goOffline(ctx: BrowserContext, page: Page) {
  await ctx.setOffline(true)
  await expect(badge(page)).toContainText('Offline', { timeout: 10_000 })
}

async function goOnline(ctx: BrowserContext, page: Page) {
  await ctx.setOffline(false)
  await expect(badge(page)).toContainText('Online', { timeout: 20_000 })
}

test.describe.serial('selling without a connection', () => {
  let ctxA: BrowserContext
  let a: Page
  let mVariant: string

  test.beforeAll(async ({ browser }) => {
    mVariant = await arrangeStock(browser, /^CLA-M-/, 5)
    ctxA = await browser.newContext()
    a = await ctxA.newPage()
    a.on('pageerror', (e) => {
      throw new Error(`Uncaught page error: ${e.message}`)
    })
    await signIn(a, CASHIER)
    await waitForCatalogue(a)
  })
  test.afterAll(async () => ctxA.close())

  test('offline: the till keeps working from the copy on this device', async () => {
    await goOffline(ctxA, a)
    await nav(a, 'Point of Sale')
    await expect(a.getByText('You are offline.')).toBeVisible()
    await addMToCart(a)
    await expect(a.getByText('1 item', { exact: true })).toBeVisible()
    await expect(a.getByText('Total (incl. GST)')).toBeVisible()
    await expect(a.getByText('The tax breakup appears on the final invoice.')).toBeVisible()
    await a.getByRole('button', { name: '+ CASH' }).click()
    await a.getByRole('button', { name: 'Complete sale (offline)' }).click()

    // A provisional receipt, clearly not a tax invoice.
    const receipt = a.getByRole('region', { name: 'Provisional receipt' })
    await expect(receipt).toContainText(/Provisional receipt · OFF-[A-Z0-9]{4}-0001/)
    await expect(receipt).toContainText('Total (GST included)')
    await expect(receipt).toContainText('This is not a GST tax invoice.')
    await expect(badge(a)).toContainText('1 saved')
  })

  test('offline: the till will not sell more than it knows it has', async () => {
    // 5 in stock, 1 already sold on this device: 4 left, and no more.
    await addMToCart(a, 4)
    await expect(a.getByLabel('Quantity', { exact: true })).toHaveText('4')
    // The fifth shirt cannot be added: the button is off, in the results and in the cart.
    await expect(a.getByRole('listitem').filter({ hasText: 'CLA-M-' }).getByRole('button', { name: 'Add' })).toBeDisabled()
    await expect(a.getByRole('button', { name: 'Increase quantity' })).toBeDisabled()
    await a.getByRole('button', { name: '+ CASH' }).click()
    await a.getByRole('button', { name: 'Complete sale (offline)' }).click()
    await expect(a.getByRole('region', { name: 'Provisional receipt' })).toContainText('-0002')
    await expect(badge(a)).toContainText('2 saved')
    // Nothing is left on the shelf as far as this device knows.
    await a.getByPlaceholder('Scan barcode or search name / SKU…').fill('Classic')
    await expect(a.getByRole('listitem').filter({ hasText: 'CLA-M-' })).toContainText('no stock left')
  })

  test('back online: the sales sync by themselves and get final tax invoices', async () => {
    await goOnline(ctxA, a)
    await nav(a, 'Sync')
    const rows = a.getByRole('region', { name: 'This device' }).getByRole('row')
    await expect(rows.filter({ hasText: 'OFF-' }).filter({ hasText: 'Synced' })).toHaveCount(2, { timeout: 30_000 })
    await expect(rows.filter({ hasText: '-0001' })).toContainText(/Invoice MAIN\/\d\d-\d\d\/\d{5}/)
    await expect(badge(a)).not.toContainText('saved')
    expect(await serverStock(a.context().browser()!, /^CLA-M-/)).toBe(0) // 5 - 1 - 4, booked once
  })

  test('connection lost during checkout: the sale is saved, and booked exactly once', async ({ browser }) => {
    await arrangeStock(browser, /^CLA-M-/, 3)
    await nav(a, 'Sync')
    await a.getByRole('button', { name: 'Refresh catalogue' }).click()
    await expect(a.getByText('Catalogue refreshed.')).toBeVisible()
    await nav(a, 'Point of Sale')
    await addMToCart(a)
    await a.getByRole('button', { name: '+ CASH' }).click()

    // The server receives and books the sale, but the reply never arrives.
    await a.route(/\/sales$/, async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      await route.fetch()
      await route.abort('connectionreset')
    })
    await a.getByRole('button', { name: 'Complete sale' }).click()
    await expect(a.getByText('The connection dropped while completing this sale')).toBeVisible()
    await expect(a.getByRole('region', { name: 'Provisional receipt' })).toBeVisible()
    await a.unroute(/\/sales$/)

    // It syncs under the same sale key: linked to the sale already made, not sold twice.
    await nav(a, 'Sync')
    await a.getByRole('button', { name: 'Sync now' }).click()
    const rows = a.getByRole('region', { name: 'This device' }).getByRole('row')
    await expect(rows.filter({ hasText: '-0003' })).toContainText('Synced', { timeout: 20_000 })
    expect(await serverStock(browser, /^CLA-M-/)).toBe(2) // 3 - 1, not 3 - 2
  })

  test('the app opens and sells after a reload with no connection', async () => {
    test.skip(!PROD, 'needs the service worker, which only exists in the production build')
    await a.reload() // let the worker settle and cache the app
    await goOffline(ctxA, a)
    await a.reload() // offline reload: served by the service worker
    // The app opens on the page it was on, as the remembered user, still knowing it is offline.
    await expect(a.getByRole('heading', { name: 'Sync status' })).toBeVisible()
    await expect(a.getByRole('banner')).toContainText('Demo Cashier')
    await expect(a.getByRole('banner')).toContainText('Main Store')
    await expect(badge(a)).toContainText('Offline')
    await nav(a, 'Point of Sale')
    await expect(a.getByText('You are offline.')).toBeVisible()
    await addMToCart(a)
    await expect(a.getByText('1 item', { exact: true })).toBeVisible()
    await goOnline(ctxA, a)
  })
})

test.describe.serial('two tills, one last shirt', () => {
  test('both sell it offline; the second to sync gets a conflict a manager resolves', async ({ browser }) => {
    await arrangeStock(browser, /^CLA-M-/, 1)

    const ctxA = await browser.newContext()
    const ctxB = await browser.newContext()
    const ctxM = await browser.newContext()
    const [a, b, m] = await Promise.all([ctxA.newPage(), ctxB.newPage(), ctxM.newPage()])
    await Promise.all([signIn(a, CASHIER), signIn(b, CASHIER), signIn(m, OWNER)])
    await Promise.all([waitForCatalogue(a), waitForCatalogue(b)])

    // Both tills go offline and each sells the single remaining shirt.
    for (const [ctx, page] of [[ctxA, a], [ctxB, b]] as const) {
      await goOffline(ctx, page)
      await nav(page, 'Point of Sale')
      await addMToCart(page)
      await page.getByRole('button', { name: '+ CASH' }).click()
      await page.getByRole('button', { name: 'Complete sale (offline)' }).click()
      await expect(page.getByRole('region', { name: 'Provisional receipt' })).toBeVisible()
    }

    // Till A reconnects first and its sale is booked.
    await goOnline(ctxA, a)
    await nav(a, 'Sync')
    await expect(a.getByRole('region', { name: 'This device' })).toContainText('Synced', { timeout: 30_000 })

    // Till B reconnects: nothing is left, so its sale is held, not lost and not silently accepted.
    await goOnline(ctxB, b)
    await nav(b, 'Sync')
    const bRows = b.getByRole('region', { name: 'This device' })
    await expect(bRows).toContainText('Needs a manager', { timeout: 30_000 })
    await expect(bRows).toContainText('Not enough stock')
    expect(await serverStock(browser, /^CLA-M-/)).toBe(0) // never negative

    // The manager sees it, with the reason, and accepts it.
    await nav(m, 'Sync')
    const held = m.getByRole('region', { name: 'Needs a manager' })
    await expect(held).toContainText('Not enough stock: Classic Cotton Shirt')
    await expect(held).toContainText('1 sold, but the system had 0')
    await held.getByRole('button', { name: 'Accept sale' }).click()
    await expect(m.getByText('No sales are waiting for a manager.')).toBeVisible({ timeout: 15_000 })

    // The stock record was wrong, so a reasoned correction sits in the ledger; stock is 0, not -1.
    expect(await serverStock(browser, /^CLA-M-/)).toBe(0)
    await nav(m, 'Inventory')
    await m.getByRole('row', { name: /CLA-M-/ }).click()
    await expect(
      m.getByText(/adjustment · Offline sale OFF-[A-Z0-9]{4}-0001 synced after stock had run out/).first(),
    ).toBeVisible()

    // Till B finds out and shows the final invoice.
    await b.getByRole('button', { name: 'Sync now' }).click()
    await expect(bRows).toContainText(/Invoice MAIN\/\d\d-\d\d\/\d{5}/, { timeout: 20_000 })

    await Promise.all([ctxA.close(), ctxB.close(), ctxM.close()])
  })
})
