# JSON Schema Reference

## Full Schema

```json
{
  "type": "object",
  "properties": {
    "title": { "type": "string" },
    "timeFrame": { "type": "string" },
    "totalIssues": { "type": "integer" },
    "criticalIssues": { "type": "integer" },
    "overallSummary": { "type": "string" },
    "criticalIssuesSummary": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "issueNumber": { "type": "integer" },
          "url": { "type": "string" },
          "title": { "type": "string" },
          "summary": { "type": "string" },
          "labels": { "type": "string" }
        },
        "required": ["issueNumber", "url", "title", "summary", "labels"]
      }
    },
    "allIssues": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "issueNumber": { "type": "integer" },
          "url": { "type": "string" },
          "title": { "type": "string" }
        },
        "required": ["issueNumber", "url", "title"]
      }
    },
    "workflowRunUrl": { "type": "string" }
  }
}
```

## Example Output

```json
{
    "title": "Daily Issue Report for Java Tooling",
    "timeFrame": "December 11, 2025",
    "totalIssues": 8,
    "criticalIssues": 3,
    "overallSummary": "Today, 8 issues were reported related to Java tooling. Among them, 3 were identified as critical based on user impact and severity.",
    "criticalIssuesSummary": [
        {
            "issueNumber": 1234,
            "url": "https://github.com/microsoft/vscode-java-pack/issues/1234",
            "title": "Java debugger crashes on Windows with JDK 21",
            "summary": "Users report debugger crashes when using JDK 21 on Windows. Investigating compatibility issues.",
            "labels": "🔴 **High Priority** | 🏷️ bug, debugger"
        },
        {
            "issueNumber": 1256,
            "url": "https://github.com/microsoft/vscode-java-pack/issues/1256",
            "title": "Add support for Java 22 preview features",
            "summary": "Request to add syntax highlighting and IntelliSense for Java 22 preview features.",
            "labels": "🟡 **Medium Priority** | 🏷️ enhancement, java-22"
        }
    ],
    "allIssues": [
        {
            "issueNumber": 1234,
            "url": "https://github.com/microsoft/vscode-java-pack/issues/1234",
            "title": "Java debugger crashes on Windows with JDK 21"
        },
        {
            "issueNumber": 1235,
            "url": "https://github.com/microsoft/vscode-java-pack/issues/1235",
            "title": "Variable view empty in debugger"
        },
        {
            "issueNumber": 1256,
            "url": "https://github.com/microsoft/vscode-java-pack/issues/1256",
            "title": "Add support for Java 22 preview features"
        }
    ],
    "workflowRunUrl": "https://github.com/chagong/issuelens/actions/runs/12345/job/67890"
}
```

## Field Guidelines

| Field | Description |
|-------|-------------|
| `summary` | Brief description including symptoms and reason for criticality |
| `labels` | Priority level + relevant issue labels |
| `overallSummary` | Keep short, no repo names |
