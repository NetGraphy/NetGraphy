# Screenshot Generation

Captures UI screenshots for the project README using Playwright.

## Prerequisites

```bash
npm install -D playwright @playwright/test
npx playwright install chromium
```

## Usage

```bash
# Against staging
export NETGRAPHY_WEB_URL=https://web-staging-a5b7.up.railway.app
export NETGRAPHY_USER=admin
export NETGRAPHY_PASS=admin

npx ts-node scripts/screenshots/capture.ts
```

## Output

Screenshots are saved to `docs/assets/screenshots/` and referenced from `README.md`.

## Captured Screens

| Screenshot | Description |
|---|---|
| dashboard.png | Main dashboard overview |
| schema-explorer.png | Schema browser showing node/edge types |
| graph-explorer.png | Graph visualization with topology |
| query-workbench.png | Cypher query editor with results |
| report-builder.png | Report builder with filters and columns |
| ai-assistant.png | AI chat panel with conversation |
| documentation.png | Auto-generated documentation |
| ai-config.png | AI provider and OTel configuration |
| device-list.png | Device list view with filters |
| device-detail.png | Device detail page with relationships |
