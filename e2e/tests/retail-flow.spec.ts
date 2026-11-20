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
    await expect(page.getByText('Welcome, Demo Owner')).toBeVisible()
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

  test('home: today strip shows the two sales', async () => {
    await nav('Wearstack')
    await expect(page.getByText('REVENUE TODAY')).toBeVisible()
    await expect(page.getByText('₹2,598.00')).toBeVisible()
    await expect(page.getByText('ORDERS TODAY').locator('xpath=..')).toContainText('2')
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

  test('the session survives a reload', async () => {
    await page.reload()
    await expect(page.getByRole('link', { name: 'Point of Sale' })).toBeVisible()
  })
})
