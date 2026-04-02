---
name: vscode-marketplace-reviews
description: Fetch and visualize reviews for any VS Code Marketplace extension. Use when (1) analyzing extension review trends, (2) getting review statistics for a time period, (3) visualizing rating distributions, (4) monitoring user feedback. Triggers on requests like "get VS Code reviews", "copilot extension feedback", "VS Code marketplace reviews", "visualize extension ratings", "analyze VS Code extension reviews".
---

# VS Code Marketplace Reviews Skill

Fetch, analyze, and visualize reviews for any extension on the VS Code Marketplace.

## Well-Known Extensions

| Extension | Publisher | Name | itemName |
|-----------|-----------|------|----------|
| GitHub Copilot Chat | `GitHub` | `copilot-chat` | `GitHub.copilot-chat` |
| GitHub Copilot | `GitHub` | `copilot` | `GitHub.copilot` |
| Python | `ms-python` | `python` | `ms-python.python` |
| Prettier | `esbenp` | `prettier-vscode` | `esbenp.prettier-vscode` |

To find the publisher and extension name, open the VS Code Marketplace page — the `itemName` query parameter contains `{publisher}.{extension}`:
`https://marketplace.visualstudio.com/items?itemName={publisher}.{extension}`

## Workflow

1. **Identify the extension**: Determine the publisher and extension name from user input (default: GitHub / copilot-chat)
2. **Determine time scope**: Parse user input for the desired time range (e.g. "last 2 weeks", "all reviews", "since 2025-06-01")
3. **Fetch reviews**: Run the fetch script with the appropriate flags
4. **Visualize**: Run the visualize script against the fetched JSON
5. **Report**: Present summary statistics and the generated chart to the user

### Email Reports

When the user requests an email report or wants charts embedded in HTML:

1. **Fetch reviews** as usual
2. **Render email charts**: Use `render_email_charts.py` to generate an HTML report with base64-encoded PNG chart images. Email clients strip `<script>` tags, so JavaScript-based charting (Chart.js, Plotly) cannot work. This script uses matplotlib to render charts server-side and embeds them as `<img src="data:image/png;base64,...">` — universally supported by email clients.
3. **Send**: Pass the HTML output as the email body via the `send-email` skill

Alternatively, use `visualize_reviews.py --base64` to get individual chart images as a JSON dict for custom HTML assembly.

## Reference Scripts

The `scripts/` directory contains **reference implementations** that the AI agent should invoke directly. The scripts accept CLI arguments so the agent can adapt them to any user request without modifying the source.

### fetch_reviews.py

Fetches reviews from the VS Code Marketplace API with full pagination support. Works with **any** extension.

```bash
# Default: GitHub Copilot Chat, last 3 weeks
py .github/skills/vscode-marketplace-reviews/scripts/fetch_reviews.py \
  --output /path/to/reviews.json

# Specific extension, last N weeks
py .github/skills/vscode-marketplace-reviews/scripts/fetch_reviews.py \
  --publisher ms-python --extension python \
  --weeks 8 --output /path/to/reviews.json

# All reviews from the beginning
py .github/skills/vscode-marketplace-reviews/scripts/fetch_reviews.py \
  --publisher GitHub --extension copilot-chat \
  --all --output /path/to/reviews.json

# Date range with full content (includes author names)
py .github/skills/vscode-marketplace-reviews/scripts/fetch_reviews.py \
  --since 2025-01-01 --until 2025-06-30 --full-content \
  --output /path/to/reviews.json
```

**CLI options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--publisher PUB` | Extension publisher name | `GitHub` |
| `--extension EXT` | Extension name | `copilot-chat` |
| `--all` | Fetch every review (paginated) | off |
| `--weeks N` | Fetch last N weeks | 3 (when no scope given) |
| `--since YYYY-MM-DD` | Start date filter | none |
| `--until YYYY-MM-DD` | End date filter | none |
| `--full-content` | Include author display name | off |
| `--output PATH` | Output JSON file path | `scripts/reviews.json` |

### visualize_reviews.py

Generates visualization charts from the JSON data. **Auto-adapts** layout and granularity based on the time span of the data:

| Time Span | Granularity | Layout |
|-----------|-------------|--------|
| ≤ 30 days | Daily | 4-panel (2×2) |
| ≤ 365 days | Weekly | 4-panel (2×2) |
| > 365 days | Monthly | 6-panel (3×2) |

```bash
py .github/skills/vscode-marketplace-reviews/scripts/visualize_reviews.py \
  --input /path/to/reviews.json --output /path/to/chart.png \
  --title "GitHub Copilot Chat" --no-show
```

**CLI options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--input PATH` | Input JSON file | `scripts/reviews.json` |
| `--output PATH` | Output PNG file | `scripts/review_analysis.png` |
| `--title TEXT` | Extension name shown in chart titles | `VS Code Extension` |
| `--no-show` | Skip interactive display | off |
| `--base64` | Output each chart as base64 PNG (JSON dict) instead of a single image file. For email embedding. | off |

When `--base64` is used, the output is a JSON file (same path but `.json` extension) containing a dict of `{chart_name: base64_png_string}` pairs. Use these to build custom HTML emails with inline `<img>` tags.

### render_email_charts.py

Renders all review charts as base64-encoded PNG images and outputs a complete HTML report fragment suitable for embedding in email bodies. This is the recommended approach for email reports since email clients strip `<script>` tags (making Chart.js/Plotly unusable).

```bash
# Generate email-ready HTML report
py .github/skills/vscode-marketplace-reviews/scripts/render_email_charts.py \
  --input /path/to/reviews.json --output /path/to/report.html \
  --title "GitHub Copilot Chat"

# Also export individual charts as JSON for custom use
py .github/skills/vscode-marketplace-reviews/scripts/render_email_charts.py \
  --input /path/to/reviews.json --output /path/to/report.html \
  --title "GitHub Copilot Chat" --json-output /path/to/charts.json
```

**CLI options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--input PATH` | Input JSON file | `../../../output/reviews.json` |
| `--output PATH` | Output HTML file | `../../../output/email_report.html` |
| `--title TEXT` | Extension name shown in titles | `VS Code Extension` |
| `--json-output PATH` | Also save chart base64 data as JSON | none |

**Charts included:**
- Rating Distribution (bar chart)
- Average Rating by Year (bar chart, long-range only)
- Monthly Review Volume (bar chart)
- Monthly Average Rating Trend (line chart with 5-bucket moving avg + neutral line)
- Monthly Rating Breakdown (stacked bar)
- Rolling Average Rating (area chart, when enough data)
- Rolling 28-Day Average Rating Trend
- Yearly Summary table, KPI cards, recent feedback tables

The output HTML uses inline styles and `<img src="data:image/png;base64,...">` tags, which are universally supported by email clients (Outlook, Gmail, Apple Mail, etc.).

### classify_reviews.py

Semantically classifies review comments into **user-defined categories** using the GitHub Models API (LLM-based). Categories are fully defined by the caller via CLI flags — nothing is hardcoded.

Each review gets a `"category"` key added (array of matching category names). An implicit `"Others"` fallback is always included.

```bash
# Classify into custom categories
py .github/skills/vscode-marketplace-reviews/scripts/classify_reviews.py \
  --input /path/to/reviews.json --output /path/to/classified.json \
  --category "Performance: Extension is slow, laggy, high CPU or memory usage" \
  --category "Rate Limiting: User complains about rate limits or token usage" \
  --category "Crash: IDE crashes, extension fails to load or terminates"

# In-place classification (output defaults to input path)
py .github/skills/vscode-marketplace-reviews/scripts/classify_reviews.py \
  --input /path/to/reviews.json \
  --category "Code Quality: Wrong or irrelevant code suggestions" \
  --category "Authentication: Login, token, or account issues"
```

**CLI options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--input PATH` | Input JSON file | `<workspace>/output/reviews.json` |
| `--output PATH` | Output JSON file | same as `--input` (in-place) |
| `--category "Name: Description"` | Category definition (repeat for each). `"Others"` is always added automatically. | *(required, at least one)* |
| `--batch-size N` | Reviews per API call | `40` |

**Environment:**

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | GitHub PAT for the GitHub Models inference API |

**How categories are built**: The agent constructs the `--category` flags from the user's natural-language request. Each flag is a `"Name: Description"` pair where **Name** is the short label and **Description** explains the semantic criteria. The script builds the LLM system prompt dynamically from these definitions.

**Output schema** — each review object gains:

```json
{
  "id": 331905,
  "date": "2026-04-01",
  "rating": 1,
  "comment": "...",
  "category": ["Performance"]
}
```

A review can belong to multiple categories (except `"Others"`, which is exclusive).

## API Details

```
GET https://marketplace.visualstudio.com/_apis/public/gallery/publishers/{publisher}/extensions/{extension}/reviews?filterOptions=1&count=100&api-version=7.2-preview.1
```

**Pagination**: The API returns reviews newest-first. Use the `beforeDate` query parameter set to the `updatedDate` of the last review in the current page to fetch the next page. The response includes `hasMoreReviews` (boolean) to indicate if more pages exist.

**Response schema:**
```json
{
  "reviews": [
    {
      "id": 331905,
      "userId": "...",
      "userDisplayName": "Author Name",
      "updatedDate": "2026-04-01T13:35:52.817Z",
      "rating": 1,
      "text": "Review comment text...",
      "productVersion": "0.43.2026040101",
      "isDeleted": false,
      "isIgnored": false
    }
  ],
  "totalReviewCount": 279,
  "hasMoreReviews": true
}
```
