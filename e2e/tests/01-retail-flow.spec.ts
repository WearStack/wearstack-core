import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'

/**
 * One shop's first day, end to end through the real UI. The steps share state (the product,
 * stock and sales built up earlier), so they run in order in a single browser page.
 *
 * The GST rate below (5%) is a TEST FIGURE, not a statement about GST law.
 */
test.describe.serial('first day in the shop', () => {
  let page: Page
  let barcode = ''
  const nav = (name: string) => page.getByRole('link', { name, exact: true }).click()

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    page.on('pageerror', (e) => {
      throw new Error(`Uncaught page error: ${e.message}`)
    })
    // A blocked script, style, image or request means the security policy and the app disagree.
    page.on('console', (m) => {
      if (m.text().includes('Content Security Policy')) throw new Error(`CSP violation: ${m.text()}`)
    })
  })
  test.afterAll(async () => page.close())

  test('first-run setup creates the business and signs the owner in', async () => {
    await page.goto('/')
    await page.waitForURL('**/setup')
    await page.getByLabel('Business name').fill('Demo Clothing Co')
    await page.getByLabel('GST state code').fill('27')
    await page.getByLabel('GSTIN (optional)').fill('27AAPFU0939F1ZV')
    await page.getByLabel('First store name').fill('Main Store')
    await page.getByLabel('Store code').fill('MAIN')
    await page.getByLabel('Your name').fill('Demo Owner')
    await page.getByLabel('Email').fill('demo@example.com')
    await page.getByLabel('Password').fill('demo-password-1')
    await page.getByRole('button', { name: 'Create business' }).click()
    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
    await expect(page.getByText('Welcome back, Demo Owner')).toBeVisible()
  })

  test('catalogue: a GST rate, then a product with variants, HSN and cost', async () => {
    await nav('Products')
    await page.getByPlaceholder('Name, e.g. Apparel').fill('Apparel')
    await page.getByPlaceholder('Rate %').fill('5')
    await page.locator('input[type=date]').first().fill('2020-01-01')
    await page.getByRole('button', { name: 'Add rate' }).click()
    await expect(page.getByText('Apparel: 5.00% from 2020-01-01')).toBeVisible()

    await page.getByLabel('Name', { exact: true }).fill('Classic Cotton Shirt')
    await page.getByLabel('Selling price (₹)').fill('1299.00')
    await page.getByLabel('Cost price (₹)').fill('700.00')
    await page.getByLabel('HSN code').fill('6205')
    await page.getByLabel('GST rate').selectOption({ label: 'Apparel (5.00%)' })
    await page.getByLabel('Sizes (comma separated)').fill('M, L')
    await page.getByRole('button', { name: 'Create product' }).click()
    await page.getByText('Classic Cotton Shirt').first().click()
    await expect(page.locator('img[alt="Barcode"]').first()).toBeVisible()
    barcode = (await page.locator('text=/^2\\d{12}$/').first().innerText()).trim()
    expect(barcode).toHaveLength(13)
  })

  test('inventory: opening stock', async () => {
    await nav('Inventory')
    await page.getByText('Classic Cotton Shirt').first().click()
    await page.getByPlaceholder('Quantity').fill('10')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('+10 → 10')).toBeVisible()
  })

  test('customers: add one in another state', async () => {
    await nav('Customers')
    await page.getByLabel('Name', { exact: true }).fill('Asha Rao')
    await page.getByLabel('Phone').fill('9876543210')
    await page.getByLabel('State code').fill('29')
    await page.getByRole('button', { name: 'Add customer' }).click()
    await expect(page.getByRole('cell', { name: 'Asha Rao' })).toBeVisible()
  })

  test('POS: scanning prices GST exactly; payment must be exact and UPI needs a reference', async () => {
    await nav('Point of Sale')
    const search = page.getByPlaceholder('Scan barcode or search name / SKU…')
    await search.fill(barcode)
    await search.press('Enter')
    await expect(page.getByText('1 item', { exact: true })).toBeVisible()
    await expect(page.getByText('Total (incl. GST)')).toBeVisible()
    await expect(page.getByText('₹1,237.14')).toBeVisible() // taxable value
    await expect(page.getByText('₹30.93')).toHaveCount(2) // CGST and SGST
    const complete = page.getByRole('button', { name: 'Complete sale' })
    await expect(complete).toBeDisabled() // no payment yet
    await page.getByRole('button', { name: '+ UPI' }).click()
    await expect(complete).toBeDisabled() // amount is right but no reference
    await page.getByLabel('upi reference').fill('UPI-TXN-998877')
    await expect(complete).toBeEnabled()
  })

  test('POS: completing the sale gives an invoice number, and the PDF opens in a new tab', async () => {
    await page.getByRole('button', { name: 'Complete sale' }).click()
    await expect(page.getByText(/Sale complete · MAIN\/\d\d-\d\d\/00001/)).toBeVisible()
    // Click it like a cashier would. The PDF viewer must render under the production CSP too.
    const link = page.getByRole('link', { name: 'Open invoice (PDF)' })
    const [tab] = await Promise.all([page.context().waitForEvent('page'), link.click()])
    expect(tab.url()).toMatch(/^blob:/)
    // Chrome renders PDFs in its built-in viewer, an extension frame. It only appears if the
    // PDF actually loaded; a CSP-blocked or broken one shows an error page without it.
    await expect
      .poll(() => tab.frames().some((f) => f.url().startsWith('chrome-extension://')))
      .toBe(true)
    await tab.close()
  })

  test('POS: an inter-state customer is charged IGST, not CGST/SGST', async () => {
    const search = page.getByPlaceholder('Scan barcode or search name / SKU…')
    await search.fill(barcode)
    await search.press('Enter')
    await page.getByPlaceholder('Customer name or phone (optional)').fill('Asha')
    await page.getByRole('button', { name: /Asha Rao/ }).click()
    await expect(page.getByText('IGST')).toBeVisible()
    await expect(page.getByText('CGST')).toHaveCount(0)
    await page.getByRole('button', { name: '+ CASH' }).click()
    await page.getByRole('button', { name: 'Complete sale' }).click()
    await expect(page.getByText(/Sale complete · MAIN\/\d\d-\d\d\/00002/)).toBeVisible()
  })

  test('POS: the quantity cannot exceed the stock on the shelf', async () => {
    const search = page.getByPlaceholder('Scan barcode or search name / SKU…')
    await search.fill(barcode)
    await search.press('Enter')
    const plus = page.getByRole('button', { name: 'Increase quantity' })
    for (let i = 0; i < 12 && (await plus.isEnabled()); i++) await plus.click()
    await expect(page.getByLabel('Quantity', { exact: true })).toHaveText('8') // 10 - 2 sold
    await page.getByRole('button', { name: 'Clear' }).click()
  })

  test('purchases: a draft changes nothing until received', async () => {
    await nav('Purchases')
    await page.getByPlaceholder('Supplier name').fill('Textile Traders')
    await page.getByRole('button', { name: 'Add supplier' }).click()
    await expect(page.locator('p', { hasText: 'Textile Traders' })).toBeVisible()
    await page.locator('label:has(span:text-is("Supplier")) select').selectOption({ label: 'Textile Traders' })
    await page.getByLabel('Supplier bill number').fill('B-100')
    await page.getByPlaceholder('Search a product or SKU to add…').fill('Classic')
    await page.getByRole('button', { name: /Classic Cotton Shirt/ }).first().click()
    await page.getByLabel(/^Quantity for/).fill('5')
    await page.getByLabel(/^Unit cost for/).fill('650.50')
    await expect(page.getByText('₹3,252.50').first()).toBeVisible()
    await page.getByRole('button', { name: 'Save as draft' }).click()
    await expect(page.getByRole('cell', { name: 'B-100' })).toBeVisible()
    await page.getByRole('button', { name: 'Receive' }).click()
    await expect(page.getByText('received', { exact: true })).toBeVisible()
  })

  test('front page: the frame shows the store and user, and the Overview matches the sales made', async () => {
    // Give the L variant a reorder level, so it shows up under Inventory alerts (stock is 8).
    await nav('Inventory')
    await page.getByText('Classic Cotton Shirt').first().click()
    await page.getByLabel('Reorder level').fill('20')
    await page.getByRole('button', { name: 'Set' }).click()

    await nav('Overview')
    // The frame (from the approved prototype): store and user in the top bar, grouped sidebar.
    const top = page.getByRole('banner')
    await expect(top).toContainText('Main Store')
    await expect(top).toContainText('Demo Owner')
    await expect(top).toContainText('Owner')
    for (const group of ['MAIN', 'CATALOGUE', 'RELATIONSHIPS', 'INSIGHTS', 'SETTINGS']) {
      await expect(page.getByRole('navigation', { name: 'Main' })).toContainText(group)
    }
    await expect(page.getByText('Returns')).toBeVisible() // arrives in a later release
    await expect(page.locator('[aria-disabled="true"]')).toContainText('Soon')

    // Today's two sales, with an honest message when there is no earlier day to compare with.
    const revenue = page.getByText('TOTAL REVENUE', { exact: true }).locator('xpath=..')
    await expect(revenue).toContainText('₹2,598.00')
    await expect(revenue).toContainText('No sales yesterday to compare with')
    await expect(page.getByText('TOTAL ORDERS', { exact: true }).locator('xpath=..')).toContainText('2')
    await expect(page.getByText('ACTIVE PRODUCTS', { exact: true }).locator('xpath=..')).toContainText('1')
    await expect(page.getByText('LOW STOCK ITEMS', { exact: true }).locator('xpath=..')).toContainText('1')
    await expect(page.getByRole('figure', { name: 'Sales performance' })).toBeVisible()

    // Inventory alerts list the variant that has reached its reorder level.
    await expect(page.getByRole('row', { name: /Classic Cotton Shirt.*8 left/ })).toBeVisible()

    // The period selector re-reads the numbers (both sales were made today).
    await page.getByLabel('Period').selectOption('month')
    await expect(page.getByText('TOTAL REVENUE', { exact: true }).locator('xpath=..')).toContainText('₹2,598.00')
    await page.getByLabel('Period').selectOption('today')

    // Quick actions go where they say.
    await page.getByRole('link', { name: /New Sale/ }).click()
    await expect(page.getByRole('heading', { name: 'Point of Sale' })).toBeVisible()
    await nav('Overview')
    await page.getByRole('button', { name: 'Start a new sale →' }).click()
    await expect(page.getByRole('heading', { name: 'Point of Sale' })).toBeVisible()
  })

  test('reports: sales totals, GST by rate, and stock agree with what was sold', async () => {
    await nav('Reports')
    await expect(page.getByText('TOTAL BILLED', { exact: true }).locator('xpath=..')).toContainText('₹2,598.00')
    await expect(page.getByText('ORDERS', { exact: true }).locator('xpath=..')).toContainText('2')
    await expect(page.getByText(/UPI ₹1,299\.00/)).toBeVisible()
    await expect(page.getByText(/CASH ₹1,299\.00/)).toBeVisible()
    await page.getByRole('tab', { name: 'GST' }).click()
    await expect(page.getByRole('cell', { name: '5.00%' })).toBeVisible()
    await page.getByRole('tab', { name: 'Stock' }).click()
    await expect(page.getByRole('row', { name: /CLA-L-.* 8/ })).toBeVisible() // 10 - 2 sold
    await expect(page.getByRole('row', { name: /CLA-M-.* 5/ })).toBeVisible() // purchase of 5
  })

  test('reports: CSV and PDF downloads contain the real data', async () => {
    await page.getByRole('tab', { name: 'Sales' }).click()
    await expect(page.getByText('TOTAL BILLED', { exact: true })).toBeVisible()
    const [csv] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'Download CSV' }).click(),
    ])
    expect(csv.suggestedFilename()).toMatch(/^sales-\d{4}-\d\d-\d\d_to_\d{4}-\d\d-\d\d\.csv$/)
    const text = (await readFile((await csv.path())!, 'utf8')).replace(/^﻿/, '')
    expect(text).toContain('Sales summary')
    expect(text).toContain('2598.00')
    const [pdf] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'Download PDF' }).click(),
    ])
    expect((await readFile((await pdf.path())!)).subarray(0, 5).toString()).toBe('%PDF-')
  })

  test('GSTIN: a store falls back to the business GSTIN; with neither, billing is blocked', async () => {
    await nav('Stores')
    await expect(page.getByText('Business GSTIN: 27AAPFU0939F1ZV')).toBeVisible()

    // Clearing the store's own GSTIN is fine: invoices carry the business GSTIN instead.
    await page.getByRole('button', { name: 'Edit GSTIN for Main Store' }).click()
    await page.getByLabel('GSTIN for Main Store').fill('')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Uses the business GSTIN (27AAPFU0939F1ZV)')).toBeVisible()

    // With no GSTIN anywhere, the screen says so and the POS refuses to price a sale.
    await page.getByRole('button', { name: 'Edit business GSTIN' }).click()
    await page.getByLabel('Business GSTIN').fill('')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Not set: billing is blocked')).toBeVisible()
    await nav('Point of Sale')
    const search = page.getByPlaceholder('Scan barcode or search name / SKU…')
    await search.fill(barcode)
    await search.press('Enter')
    await expect(page.getByText(/Add your GSTIN in Stores before billing/)).toBeVisible()
    await page.getByRole('button', { name: 'Clear' }).click()
  })

  test('GSTIN: a mistyped GSTIN is rejected, a correct one restores billing', async () => {
    await nav('Stores')
    await page.getByRole('button', { name: 'Add business GSTIN' }).click()
    await page.getByLabel('Business GSTIN').fill('27AAPFU0939F1ZW') // wrong check character
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText(/valid GSTIN/i)).toBeVisible()
    await page.getByLabel('Business GSTIN').fill('27aapfu0939f1zv') // lower case is normalised
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Business GSTIN: 27AAPFU0939F1ZV')).toBeVisible()
    await expect(page.getByText('Uses the business GSTIN (27AAPFU0939F1ZV)')).toBeVisible()

    await nav('Point of Sale')
    const search = page.getByPlaceholder('Scan barcode or search name / SKU…')
    await search.fill(barcode)
    await search.press('Enter')
    await expect(page.getByText('Total (incl. GST)')).toBeVisible()
    await page.getByRole('button', { name: 'Clear' }).click()
  })

  test('sign-in page: layout, validation, wrong password, show/hide and forgot password', async () => {
    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await page.waitForURL('**/login')
    // The split layout from the approved prototype.
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
    await expect(page.getByText('Sign in to your Wearstack workspace.')).toBeVisible()
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Your store.')
    for (const feature of ['Fast billing', 'Smart inventory', 'Business insights']) {
      await expect(page.getByText(feature)).toBeVisible()
    }
    await expect(page.getByText('BUILT FOR THE WAY YOU RETAIL.')).toBeVisible()
    await expect(page.getByLabel('Remember me')).not.toBeChecked() // the safe default

    // Empty and malformed input is explained before anything is sent.
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByText('Enter a valid email address')).toBeVisible()
    await expect(page.getByText('Enter your password')).toBeVisible()

    // A wrong password gives one generic message (it never says which half was wrong).
    await page.getByLabel('Email address').fill('demo@example.com')
    await page.getByLabel('Password').fill('not-the-password')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('alert')).toHaveText('Invalid email or password')

    // Show / Hide toggles the field type.
    const password = page.getByLabel('Password')
    await expect(password).toHaveAttribute('type', 'password')
    await page.getByRole('button', { name: 'Show' }).click()
    await expect(password).toHaveAttribute('type', 'text')
    await page.getByRole('button', { name: 'Hide' }).click()
    await expect(password).toHaveAttribute('type', 'password')

    // There is no email reset yet, and the screen says so instead of pretending.
    await page.getByRole('button', { name: 'Forgot password?' }).click()
    await expect(page.getByRole('alert')).toContainText('Ask your store owner or administrator')
    // A production build never offers a way around signing in.
    const demo = page.getByRole('button', { name: 'Explore demo dashboard' })
    await expect(demo).toHaveCount(process.env.E2E_PROD ? 0 : 1)
  })

  test('remember me: unticked ends with the browser session, ticked lasts for days', async () => {
    const refreshCookie = async () =>
      (await page.context().cookies()).find((c) => c.name === 'refresh_token')

    await page.getByLabel('Email address').fill('demo@example.com')
    await page.getByLabel('Password').fill('demo-password-1')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
    expect((await refreshCookie())?.expires).toBe(-1) // a session cookie

    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await page.waitForURL('**/login')
    await page.getByLabel('Email address').fill('demo@example.com')
    await page.getByLabel('Password').fill('demo-password-1')
    await page.getByLabel('Remember me').check()
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
    const days = ((await refreshCookie())!.expires - Date.now() / 1000) / 86400
    expect(days).toBeGreaterThan(13)
    expect(days).toBeLessThanOrEqual(14)
  })

  test('a cashier created by the owner can sign in and sees only what the role allows', async () => {
    await nav('Admin')
    await page.getByLabel('Full name').fill('Demo Cashier')
    await page.getByLabel('Email').fill('cashier@example.com')
    await page.getByLabel('Temporary password').fill('cashier-password-1')
    await page.getByLabel('Role').selectOption({ label: 'Cashier' })
    await page.getByLabel('Main Store').check()
    await page.getByRole('button', { name: 'Create user' }).click()
    await expect(page.getByRole('cell', { name: /cashier@example\.com/ })).toBeVisible()
    // Not signed in yet, and still on a temporary password.
    const row = page.getByRole('row', { name: /cashier@example\.com/ })
    await expect(row).toContainText('Never')
    await expect(row).toContainText('Must choose a password')

    // The cashier "forgot" the temporary password: the owner sets a new one.
    await page.getByRole('button', { name: 'Reset password for Demo Cashier' }).click()
    await page.getByLabel('New password for Demo Cashier').fill('cashier-password-2')
    await page.getByRole('button', { name: 'Set password', exact: true }).click()
    await expect(page.getByText('Password changed for Demo Cashier')).toBeVisible()

    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await page.waitForURL('**/login')
    await page.getByLabel('Email address').fill('cashier@example.com')
    await page.getByLabel('Password').fill('cashier-password-1') // the old one no longer works
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('alert')).toHaveText('Invalid email or password')
    await page.getByLabel('Password').fill('cashier-password-2')
    await page.getByRole('button', { name: 'Sign in' }).click()

    // A temporary password must be replaced before anything else can be done.
    await expect(page.getByRole('heading', { name: 'Choose your own password' })).toBeVisible()
    await page.goto('/pos') // trying to skip ahead leads straight back
    await expect(page.getByRole('heading', { name: 'Choose your own password' })).toBeVisible()
    const submit = page.getByRole('button', { name: 'Set my password' })
    await page.getByLabel('Temporary password').fill('cashier-password-2')
    await page.getByLabel('New password', { exact: true }).fill('short')
    await submit.click()
    await expect(page.getByText('Use at least 10 characters')).toBeVisible()
    await page.getByLabel('New password', { exact: true }).fill('cashier-password-2')
    await page.getByLabel('Confirm new password').fill('cashier-password-2')
    await submit.click()
    await expect(page.getByText('Choose a password different from the temporary one')).toBeVisible()
    await page.getByLabel('New password', { exact: true }).fill('cashier-final-pass-3')
    await page.getByLabel('Confirm new password').fill('cashier-final-pass-9')
    await submit.click()
    await expect(page.getByText('The passwords do not match')).toBeVisible()
    await page.getByLabel('Confirm new password').fill('cashier-final-pass-3')
    await submit.click()
    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()

    // The cashier works in a store even though the role cannot browse the Stores screen.
    await expect(page.getByRole('banner')).toContainText('Main Store')
    await expect(page.getByRole('banner')).toContainText('Cashier')
    const menu = page.getByRole('navigation', { name: 'Main' })
    for (const hidden of ['Reports', 'Stores', 'Admin', 'Roles', 'Purchases']) {
      await expect(menu.getByRole('link', { name: hidden, exact: true })).toHaveCount(0)
    }
    await expect(menu.getByRole('link', { name: 'Point of Sale', exact: true })).toBeVisible()
    // No revenue figures for a cashier, but the shelf alerts and the sale button are there.
    await expect(page.getByText('TOTAL REVENUE', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('row', { name: /Classic Cotton Shirt.*8 left/ })).toBeVisible()
    await page.goto('/reports')
    await expect(page.getByText("You don't have access to this page.")).toBeVisible()
  })

  test('the cashier completes a sale at the till', async () => {
    await nav('Point of Sale')
    const search = page.getByPlaceholder('Scan barcode or search name / SKU…')
    await search.fill(barcode)
    await search.press('Enter')
    await expect(page.getByText('Total (incl. GST)')).toBeVisible()
    await page.getByRole('button', { name: '+ CASH' }).click()
    await page.getByRole('button', { name: 'Complete sale' }).click()
    await expect(page.getByText(/Sale complete · MAIN\/\d\d-\d\d\/00003/)).toBeVisible()
  })

  test('the session survives a reload', async () => {
    await page.reload()
    await expect(page.getByRole('link', { name: 'Point of Sale' })).toBeVisible()
  })
})
