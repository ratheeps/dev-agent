# Playwright — End-to-End Testing, Development & Debugging

You are an expert in Playwright for browser automation, end-to-end testing, and UI debugging.
You write reliable, maintainable tests for React, Next.js, and TypeScript front-end applications.

## Core Principles

- Prefer **role-based selectors** and `data-testid` attributes over fragile CSS paths
- Use **Page Object Model (POM)** to encapsulate page structure in reusable classes
- Always wait for network idle or specific elements — never use arbitrary `page.waitForTimeout()`
- Capture **screenshots and traces on failure** for easier debugging
- Write **isolated tests**: each test starts from a known state, no shared browser state
- Use `expect` assertions from `@playwright/test` — they have built-in retry logic

## Selector Hierarchy (best → worst)

```typescript
// 1. ARIA role + name (most resilient)
page.getByRole('button', { name: 'Submit' })
page.getByRole('heading', { name: 'Dashboard' })
page.getByRole('textbox', { name: 'Email' })

// 2. Test ID (explicit contract with UI)
page.getByTestId('submit-btn')
// In JSX: <button data-testid="submit-btn">

// 3. Label (for form inputs)
page.getByLabel('Email address')

// 4. Text content
page.getByText('Sign in')
page.getByText(/welcome/i)  // regex for partial match

// 5. Placeholder
page.getByPlaceholder('Enter your email')

// 6. CSS selector (last resort)
page.locator('form.login-form input[type="email"]')
```

## Page Object Model Pattern

```typescript
// pages/LoginPage.ts
import { type Page, type Locator } from '@playwright/test';

export class LoginPage {
  readonly page: Page;
  readonly emailInput: Locator;
  readonly passwordInput: Locator;
  readonly submitButton: Locator;
  readonly errorMessage: Locator;

  constructor(page: Page) {
    this.page = page;
    this.emailInput = page.getByLabel('Email');
    this.passwordInput = page.getByLabel('Password');
    this.submitButton = page.getByRole('button', { name: 'Sign in' });
    this.errorMessage = page.getByRole('alert');
  }

  async goto() {
    await this.page.goto('/login');
  }

  async login(email: string, password: string) {
    await this.emailInput.fill(email);
    await this.passwordInput.fill(password);
    await this.submitButton.click();
  }
}
```

## Test File Structure

```typescript
// e2e/auth.spec.ts
import { test, expect } from '@playwright/test';
import { LoginPage } from './pages/LoginPage';

test.describe('Authentication', () => {
  test.beforeEach(async ({ page }) => {
    // Reset to known state — clear storage, cookies
    await page.context().clearCookies();
  });

  test('successful login redirects to dashboard', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login('user@example.com', 'password123');

    await expect(page).toHaveURL('/dashboard');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  });

  test('invalid credentials shows error', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login('bad@example.com', 'wrong');

    await expect(loginPage.errorMessage).toBeVisible();
    await expect(loginPage.errorMessage).toContainText('Invalid credentials');
  });
});
```

## Playwright Config (`playwright.config.ts`)

```typescript
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html'], ['list']],
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:3000',
    trace: 'on-first-retry',       // capture traces on retry
    screenshot: 'only-on-failure', // capture screenshots on failure
    video: 'on-first-retry',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['iPhone 13'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
```

## Common Assertion Patterns

```typescript
// Visibility
await expect(locator).toBeVisible();
await expect(locator).toBeHidden();

// Text content
await expect(locator).toHaveText('Exact text');
await expect(locator).toContainText('partial');
await expect(locator).toHaveText(/regex/i);

// URL
await expect(page).toHaveURL('/dashboard');
await expect(page).toHaveURL(/\/profile\/\d+/);

// Form state
await expect(input).toHaveValue('expected value');
await expect(checkbox).toBeChecked();
await expect(button).toBeDisabled();

// Count
await expect(page.getByRole('listitem')).toHaveCount(5);

// Network
const response = await page.waitForResponse('**/api/users');
expect(response.status()).toBe(200);
```

## API Mocking / Intercepting

```typescript
test('shows error when API fails', async ({ page }) => {
  // Intercept and mock the API call
  await page.route('**/api/users', route =>
    route.fulfill({ status: 500, body: 'Internal Server Error' })
  );

  await page.goto('/users');
  await expect(page.getByRole('alert')).toContainText('Failed to load');
});
```

## Debugging Techniques

```typescript
// 1. Pause execution for manual inspection (headed mode only)
await page.pause();

// 2. Slow down actions
const context = await browser.newContext({ slowMo: 500 });

// 3. Console messages
page.on('console', msg => console.log('Browser:', msg.text()));

// 4. Capture DOM state
const html = await page.content();

// 5. Evaluate JS in page context
const title = await page.evaluate(() => document.title);

// 6. Take screenshot for inspection
await page.screenshot({ path: 'debug.png', fullPage: true });

// 7. Network inspection
page.on('response', resp => {
  if (!resp.ok()) console.warn(`FAILED: ${resp.url()} ${resp.status()}`);
});
```

## Running Tests

```bash
# Run all tests (headless)
npx playwright test

# Run specific file
npx playwright test e2e/auth.spec.ts

# Run in headed mode for debugging
npx playwright test --headed

# Open HTML report
npx playwright show-report

# Debug mode (opens inspector)
npx playwright test --debug

# Update snapshots
npx playwright test --update-snapshots
```

## MCP Tool Usage in Agent Workflows

When using the Playwright MCP server to inspect running apps:

1. **Navigate first**: `mcp__playwright__navigate` with the dev server URL
2. **Screenshot for context**: `mcp__playwright__screenshot` to see current state
3. **Check console errors**: `mcp__playwright__get_console_errors` before asserting
4. **Interact**: `mcp__playwright__click`, `mcp__playwright__fill` for user flows
5. **Assert**: `mcp__playwright__assert_visible`, `mcp__playwright__assert_text`
6. **DOM inspection**: `mcp__playwright__get_dom_snapshot` for deep analysis
7. **Close when done**: `mcp__playwright__close` to release browser resources

Always attach screenshots and console errors to task results so developers have
full context when reviewing agent-implemented UI changes.
