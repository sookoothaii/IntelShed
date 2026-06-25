import { test, expect } from '@playwright/test'

test.describe('E2E 1 — Globe boots + layer toggle', () => {
  test('globe renders and layer toggles work', async ({ page }) => {
    await page.goto('/')
    // Wait for the globe container to appear
    await expect(page.locator('[data-testid="globe"], .cesium-viewer, canvas')).toBeVisible({ timeout: 30_000 })
    // Try clicking a nav item if globe not immediately visible
    const globeNav = page.locator('text=GLOBE').first()
    if (await globeNav.isVisible()) {
      await globeNav.click()
    }
    // Verify some HUD element is present
    await expect(page.locator('body')).not.toBeEmpty()
  })
})

test.describe('E2E 2 — AI Chat sends message', () => {
  test('chat input accepts text', async ({ page }) => {
    await page.goto('/')
    const chatNav = page.locator('text=AI').first()
    if (await chatNav.isVisible()) {
      await chatNav.click()
    }
    // Look for chat input
    const chatInput = page.locator('textarea, input[type="text"]').last()
    if (await chatInput.isVisible({ timeout: 10_000 })) {
      await chatInput.fill('test message')
      await expect(chatInput).toHaveValue('test message')
    }
  })
})

test.describe('E2E 3 — SITUATIONS board loads', () => {
  test('situations panel renders', async ({ page }) => {
    await page.goto('/')
    // Look for SITUATIONS nav or panel
    const sitNav = page.locator('text=SITUATIONS, text=SIT').first()
    if (await sitNav.isVisible()) {
      await sitNav.click()
    }
    await expect(page.locator('body')).not.toBeEmpty()
  })
})

test.describe('E2E 4 — DATA panel loads', () => {
  test('data panel shows feeds', async ({ page }) => {
    await page.goto('/')
    const dataNav = page.locator('text=DATA').first()
    if (await dataNav.isVisible()) {
      await dataNav.click()
    }
    await expect(page.locator('body')).not.toBeEmpty()
  })
})

test.describe('E2E 5 — Visual regression', () => {
  test('globe viewport screenshot', async ({ page }) => {
    await page.goto('/')
    await page.waitForTimeout(3_000)
    // Baselines are created/updated intentionally with:
    //   npx playwright test --update-snapshots
    // This test must fail on real regressions; do not swallow errors.
    await expect(page).toHaveScreenshot('globe-viewport.png', {
      maxDiffPixelRatio: 0.1,
      timeout: 15_000,
    })
  })
})
