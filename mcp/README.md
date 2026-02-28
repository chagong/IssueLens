# IssueLens MCP Server

Streamable HTTP MCP server for semantic search over Java Tooling GitHub issue data indexed in Azure AI Search.

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in your Azure AI Search credentials:

```bash
cp .env.example .env
```

3. Run the server:

```bash
python server.py
```

The server starts on `http://0.0.0.0:8000` by default (configurable via `MCP_SERVER_HOST` / `MCP_SERVER_PORT`).

## MCP Tool

### `search_issues`

Semantic search over Java Tooling GitHub issues.

| Parameter     | Type   | Default | Description                                      |
|---------------|--------|---------|--------------------------------------------------|
| `query`       | string | —       | Natural-language search query                    |
| `max_results` | int    | 10      | Maximum number of results to return (1–50)       |

Returns an array of results with fields: `title`, `fullText`, `url`, `repository`, `createdDate`, `rootItemPath`, `repoItemPath`, `parentItemPath`, `adoDevComPostId`, `tags`, `score`, `chunk`.

## VS Code / Copilot Configuration

Add to your `.vscode/mcp.json`:

```json
{
  "servers": {
    "issuelens-search": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```
