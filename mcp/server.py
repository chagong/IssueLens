"""
IssueLens MCP Server - Semantic search over Java Tooling issue data via Azure AI Search.

Streamable HTTP MCP server that exposes a `search_issues` tool.
"""

import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizableTextQuery

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

AZURE_SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
AZURE_SEARCH_INDEX_NAME = os.environ["AZURE_SEARCH_INDEX_NAME"]
MCP_SERVER_HOST = os.environ.get("MCP_SERVER_HOST", "0.0.0.0")
MCP_SERVER_PORT = int(os.environ.get("MCP_SERVER_PORT", "8000"))

# ---------------------------------------------------------------------------
# Azure AI Search client
# ---------------------------------------------------------------------------

credential = DefaultAzureCredential()
search_client = SearchClient(
    endpoint=AZURE_SEARCH_ENDPOINT,
    index_name=AZURE_SEARCH_INDEX_NAME,
    credential=credential,
)

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "IssueLens Search",
    instructions=(
        "Semantic search over Java Tooling GitHub issue data. "
        "Use the search_issues tool to find issues by natural-language query."
    ),
    host=MCP_SERVER_HOST,
    port=MCP_SERVER_PORT,
)


@dataclass
class SearchResult:
    """Single search result matching the IssueLens index schema."""

    title: str = ""
    full_text: str = ""
    url: str = ""
    repository: str = ""
    created_date: str = ""
    root_item_path: str = ""
    repo_item_path: str = ""
    parent_item_path: str | None = None
    ado_dev_com_post_id: int = 0
    tags: list[dict[str, Any]] = field(default_factory=list)
    score: float | None = None
    chunk: str = ""


def _to_result(doc: dict[str, Any]) -> dict[str, Any]:
    """Map an Azure Search document to the SearchResult schema."""
    return {
        "title": doc.get("Title", ""),
        "fullText": doc.get("FullText", ""),
        "url": doc.get("Url", ""),
        "repository": doc.get("Repository", ""),
        "createdDate": doc.get("CreatedDate", ""),
        "rootItemPath": doc.get("RootItemPath", ""),
        "repoItemPath": doc.get("RepoItemPath", ""),
        "parentItemPath": doc.get("ParentItemPath"),
        "adoDevComPostId": doc.get("AdoDevComPostId", 0),
        "tags": doc.get("Tags", []),
        "score": doc.get("@search.score"),
        "chunk": doc.get("chunk", ""),
    }


@mcp.tool()
def search_issues(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Search Java Tooling GitHub issues using semantic search.

    Args:
        query: Natural-language search query describing the issues to find.
        max_results: Maximum number of results to return (1-50, default 10).
    """
    max_results = max(1, min(max_results, 50))

    vector_query = VectorizableTextQuery(
        text=query,
        k_nearest_neighbors=max_results,
        fields="text_vector",
    )

    results = search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        top=max_results,
    )

    return [_to_result(doc) for doc in results]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    from starlette.middleware.cors import CORSMiddleware

    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )

    uvicorn.run(app, host=MCP_SERVER_HOST, port=MCP_SERVER_PORT)
