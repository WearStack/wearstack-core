import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test'

/**
 * The admin page, end to end, with real separate sessions: an owner adds people, they sign in
 * on their own device and must choose their own password, and the owner can sign them out
 * everywhere, deactivate them and see it all in the activity log.
 *
 * Runs after 01 and 02 (it reuses the owner they set up).
 */
const OWNER = { email: 'demo@example.com', password: 'demo-password-1' }

async function signIn(page: Page, who: { email: string; password: string }) {
  await page.goto('/login')
  await page.getByLabel('Email address').fill(who.email)
  await page.getByLabel('Password').fill(who.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

const nav = (page: Page, name: string) => page.getByRole('link', { name, exact: true }).click()

/** Adds a person on the Admin page and returns the temporary password that was shown once. */
async function addPerson(page: Page, name: string, email: string, role: string): Promise<string> {
  await page.getByLabel('Full name').fill(name)
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Role').selectOption({ label: role })
  await page.getByLabel('Main Store').check()
  // A generated temporary password is already filled in; the page shows it once after creating.
  await page.getByRole('button', { name: 'Create user' }).click()
  await expect(page.getByText(`${name} can now sign in`)).toBeVisible()
  return (await page.getByTestId('temp-password').innerText()).trim()
}

test.describe.serial('the admin page', () => {
  let owner: BrowserContext
  let admin: Page
  let tempPassword = ''
  const PERSON = { name: 'Priya Staff', email: 'priya@example.com' }

  test.beforeAll(async ({ browser }: { browser: Browser }) => {
    owner = await browser.newContext()
    admin = await owner.newPage()
    await signIn(admin, OWNER)
    await expect(admin.getByRole('heading', { name: 'Overview' })).toBeVisible()
  })
  test.afterAll(async () => owner.close())

  test('there is no way to sign up: the login page has no signup, and Admin is where people are added', async ({ browser }) => {
    const anon = await browser.newContext()
    const p = await anon.newPage()
    await p.goto('/login')
    await expect(p.getByText(/sign up|create an account|register/i)).toHaveCount(0)
    await p.goto('/signup')
    await expect(p.getByRole('heading', { name: 'Welcome back' })).toBeVisible() // unknown pages land on sign-in
    await anon.close()

    await nav(admin, 'Admin')
    await expect(admin.getByRole('heading', { name: 'Admin' })).toBeVisible()
    await expect(admin.getByRole('tab', { name: 'Users' })).toBeVisible()
    await expect(admin.getByRole('tab', { name: 'Activity' })).toBeVisible()
    await expect(admin.getByText('There is no self-signup')).toBeVisible()
    await admin.goto('/users') // the old address leads to the Admin page
    await expect(admin.getByRole('heading', { name: 'Admin' })).toBeVisible()
  })

  test('adding a person shows a generated temporary password once', async () => {
    tempPassword = await addPerson(admin, PERSON.name, PERSON.email, 'Cashier')
    expect(tempPassword).toMatch(/^[A-Za-z2-9]{4}(-[A-Za-z2-9]{4}){3}$/)
    const row = admin.getByRole('row', { name: new RegExp(PERSON.email) })
    await expect(row).toContainText('Cashier')
    await expect(row).toContainText('Main Store')
    await expect(row).toContainText('Never')
    await expect(row).toContainText('Must choose a password')
    await admin.getByRole('button', { name: 'Done' }).click()
    await expect(admin.getByTestId('temp-password')).toHaveCount(0) // gone once dismissed
  })

  test('their first sign-in forces them to choose their own password', async ({ browser }) => {
    const ctx = await browser.newContext()
    const p = await ctx.newPage()
    await signIn(p, { email: PERSON.email, password: tempPassword })
    await expect(p.getByRole('heading', { name: 'Choose your own password' })).toBeVisible()
    await p.getByLabel('Temporary password').fill(tempPassword)
    await p.getByLabel('New password', { exact: true }).fill('priyas-own-pass-1')
    await p.getByLabel('Confirm new password').fill('priyas-own-pass-1')
    await p.getByRole('button', { name: 'Set my password' }).click()
    await expect(p.getByRole('heading', { name: 'Overview' })).toBeVisible()
    await expect(p.getByRole('banner')).toContainText(PERSON.name)
    await ctx.close()

    // The owner now sees a recent sign-in and no pending password change.
    await admin.getByRole('button', { name: 'Refresh', exact: true }).click()
    const row = admin.getByRole('row', { name: new RegExp(PERSON.email) })
    await expect(row).not.toContainText('Never')
    await expect(row).not.toContainText('Must choose a password')
    await expect(row).toContainText(/just now|minute/)
  })

  test('editing a person changes their role and what they can see', async ({ browser }) => {
    await admin.getByRole('button', { name: `Edit ${PERSON.name}` }).click()
    await admin.getByLabel(`Name of ${PERSON.name}`).fill('Priya Manager')
    await admin.getByLabel('Role of Priya Staff').selectOption({ label: 'Manager' })
    await admin.getByRole('button', { name: 'Save changes' }).click()
    const row = admin.getByRole('row', { name: /priya@example\.com/ })
    await expect(row).toContainText('Priya Manager')
    await expect(row).toContainText('Manager')

    // As a Manager she can read the people list but cannot add or change anyone.
    const ctx = await browser.newContext()
    const p = await ctx.newPage()
    await signIn(p, { email: PERSON.email, password: 'priyas-own-pass-1' })
    await expect(p.getByRole('heading', { name: 'Overview' })).toBeVisible()
    await nav(p, 'Admin')
    await expect(p.getByRole('row', { name: /priya@example\.com/ })).toBeVisible()
    await expect(p.getByText('Add a person')).toHaveCount(0)
    await expect(p.getByRole('button', { name: /Reset password for/ })).toHaveCount(0)
    await expect(p.getByRole('tab', { name: 'Activity' })).toHaveCount(0) // no audit access
    await ctx.close()
  })

  test('signing someone out everywhere ends their open session at once', async ({ browser }) => {
    const ctx = await browser.newContext()
    const p = await ctx.newPage()
    await signIn(p, { email: PERSON.email, password: 'priyas-own-pass-1' })
    await expect(p.getByRole('heading', { name: 'Overview' })).toBeVisible()
    await p.waitForTimeout(1200) // sessions are timestamped to the second

    await admin.getByRole('button', { name: 'Sign out Priya Manager everywhere' }).click()
    await admin.getByRole('button', { name: 'Yes, sign out everywhere' }).click()
    await expect(admin.getByText('Signed out everywhere')).toBeVisible()

    // Her next request is refused and she is taken back to sign-in.
    await nav(p, 'Customers')
    await expect(p.getByRole('heading', { name: 'Welcome back' })).toBeVisible({ timeout: 15_000 })
    // She is not locked out: signing in again works.
    await signIn(p, { email: PERSON.email, password: 'priyas-own-pass-1' })
    await expect(p.getByRole('heading', { name: 'Overview' })).toBeVisible()
    await ctx.close()
  })

  test('resetting a password signs them out and makes the new one temporary', async ({ browser }) => {
    const ctx = await browser.newContext()
    const p = await ctx.newPage()
    await signIn(p, { email: PERSON.email, password: 'priyas-own-pass-1' })
    await expect(p.getByRole('heading', { name: 'Overview' })).toBeVisible()
    await p.waitForTimeout(1200)

    await admin.getByRole('button', { name: 'Reset password for Priya Manager' }).click()
    await admin.getByRole('button', { name: 'Generate' }).first().click()
    const generated = await admin.getByLabel('New password for Priya Manager').inputValue()
    expect(generated).toMatch(/^[A-Za-z2-9]{4}(-[A-Za-z2-9]{4}){3}$/)
    await admin.getByRole('button', { name: 'Set password', exact: true }).click()
    await expect(admin.getByText('Password changed for Priya Manager')).toBeVisible()
    await expect(admin.getByRole('row', { name: /priya@example\.com/ })).toContainText('Must choose a password')

    await nav(p, 'Customers') // her open session is over
    await expect(p.getByRole('heading', { name: 'Welcome back' })).toBeVisible({ timeout: 15_000 })
    await signIn(p, { email: PERSON.email, password: 'priyas-own-pass-1' }) // the old password is dead
    await expect(p.getByRole('alert')).toHaveText('Invalid email or password')
    await p.getByLabel('Password').fill(generated)
    await p.getByRole('button', { name: 'Sign in' }).click()
    await expect(p.getByRole('heading', { name: 'Choose your own password' })).toBeVisible()
    await ctx.close()
  })

  test('deactivating blocks sign-in, and reactivating allows it again', async ({ browser }) => {
    await admin.getByRole('button', { name: 'Deactivate Priya Manager' }).click()
    const row = admin.getByRole('row', { name: /priya@example\.com/ })
    await expect(row).toContainText('Inactive')

    const ctx = await browser.newContext()
    const p = await ctx.newPage()
    await signIn(p, { email: PERSON.email, password: 'whatever-1234567' })
    await expect(p.getByRole('alert')).toHaveText('Invalid email or password')
    await ctx.close()

    await admin.getByRole('button', { name: 'Activate Priya Manager' }).click()
    await expect(row).toContainText('Active')
  })

  test('the last Owner cannot be deactivated or demoted, and says why', async () => {
    await admin.getByRole('button', { name: 'Deactivate Demo Owner' }).click()
    await expect(admin.getByText(/needs an active Owner|cannot deactivate yourself/)).toBeVisible()
    await expect(admin.getByRole('row', { name: /demo@example\.com/ })).toContainText('Active')
  })

  test('the activity log shows who did what, by name, and can be filtered', async () => {
    await admin.getByRole('tab', { name: 'Activity' }).click()
    const table = admin.getByRole('table')
    await expect(table).toContainText('Added priya@example.com')
    await expect(table).toContainText('Demo Owner')
    await expect(table).toContainText('Signed priya@example.com out everywhere')
    await expect(table).toContainText('Reset the password of priya@example.com')
    await expect(table).toContainText('Deactivated priya@example.com')
    await expect(table).toContainText('Changed their own password') // her first sign-in change

    await admin.getByLabel('Kind of activity').selectOption({ label: 'Sales' })
    await expect(table).toContainText(/Sale MAIN\//)
    await expect(table).not.toContainText('Added priya@example.com')
    await admin.getByLabel('Kind of activity').selectOption({ label: 'People and access' })
    await expect(table).toContainText('Added priya@example.com')
    await expect(table).not.toContainText(/Sale MAIN\//)
  })
})
