import { test, expect, type Page } from '@playwright/test'

/**
 * E-05 Visual Regression — golden screenshots per panel × theme.
 *
 * Themes:  cyber (dark, default) + mss (light)
 * Panels:  Globe, DataPanel, ChatPanel, SituationBoard, BriefingKanban
 *
 * Baselines are created/updated with:
 *   npx playwright test visual.spec.ts --update-snapshots
 * or via the npm script:
 *   npm run test:e2e:visual:update
 *
 * In CI these are skipped (Cesium needs a real Ion token + WebGL).
 */

const THEMES = ['cyber', 'mss'] as const
type Theme = (typeof THEMES)[number]

async function setTheme(page: Page, theme: Theme) {
  await page.evaluate((t) => {
    localStorage.setItem('worldbase-theme', t)
    if (t === 'mss') {
      document.documentElement.setAttribute('data-theme', 'mss')
    } else {
      document.documentElement.removeAttribute('data-theme')
    }
  }, theme)
}

async function navigateToView(page: Page, label: string) {
  const nav = page.locator(`text=${label}`).first()
  if (await nav.isVisible({ timeout: 5_000 })) {
    await nav.click()
    await page.waitForTimeout(1_500) // allow lazy component to mount
  }
}

for (const theme of THEMES) {
  test.describe(`Visual regression — ${theme} theme`, () => {
    test.skip(!!process.env.CI, 'Visual regression needs real Cesium token + WebGL — skipped in CI')

    test(`Globe — ${theme}`, async ({ page }) => {
      await page.goto('/')
      await setTheme(page, theme)
      await page.reload()
      await navigateToView(page, 'GLOBE')
      await expect(page.locator('canvas, .cesium-viewer').first()).toBeVisible({ timeout: 30_000 })
      await page.waitForTimeout(3_000) // let Cesium settle
      await expect(page).toHaveScreenshot(`globe-${theme}.png`, {
        maxDiffPixelRatio: 0.1,
        timeout: 15_000,
        animations: 'disabled',
      })
    })

    test(`DataPanel — ${theme}`, async ({ page }) => {
      await page.goto('/')
      await setTheme(page, theme)
      await page.reload()
      await navigateToView(page, 'DATA')
      await page.waitForTimeout(1_500)
      await expect(page).toHaveScreenshot(`data-panel-${theme}.png`, {
        maxDiffPixelRatio: 0.05,
        timeout: 15_000,
        animations: 'disabled',
      })
    })

    test(`ChatPanel — ${theme}`, async ({ page }) => {
      await page.goto('/')
      await setTheme(page, theme)
      await page.reload()
      await navigateToView(page, 'AI')
      await page.waitForTimeout(1_500)
      await expect(page).toHaveScreenshot(`chat-panel-${theme}.png`, {
        maxDiffPixelRatio: 0.05,
        timeout: 15_000,
        animations: 'disabled',
      })
    })

    test(`SituationBoard — ${theme}`, async ({ page }) => {
      await page.goto('/')
      await setTheme(page, theme)
      await page.reload()
      // SituationBoard is opened via the SITUATIONS button/panel
      const sitBtn = page.locator('text=SITUATIONS, text=SIT').first()
      if (await sitBtn.isVisible({ timeout: 5_000 })) {
        await sitBtn.click()
        await page.waitForTimeout(1_500)
      }
      await expect(page).toHaveScreenshot(`situation-board-${theme}.png`, {
        maxDiffPixelRatio: 0.05,
        timeout: 15_000,
        animations: 'disabled',
      })
    })

    test(`BriefingKanban — ${theme}`, async ({ page }) => {
      await page.goto('/')
      await setTheme(page, theme)
      await page.reload()
      // BriefingKanban may be behind a button or nav item
      const kanbanBtn = page.locator('text=BRIEFING, text=KANBAN').first()
      if (await kanbanBtn.isVisible({ timeout: 5_000 })) {
        await kanbanBtn.click()
        await page.waitForTimeout(1_500)
      }
      await expect(page).toHaveScreenshot(`briefing-kanban-${theme}.png`, {
        maxDiffPixelRatio: 0.05,
        timeout: 15_000,
        animations: 'disabled',
      })
    })
  })
}
