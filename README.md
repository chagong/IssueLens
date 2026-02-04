# IssueLens

IssueLens is a GitHub Copilot-powered issue triage system that combines custom agents and modular skills to automate issue management across **multiple GitHub repositories**. It supports daily triage, SLA compliance checking, automatic labeling, and multi-channel notifications.

## Features

- **Automated Issue Triage**: Identify hot, blocking, and regression issues
- **SLA Compliance Checking**: Verify issues meet SLA requirements with detailed reports
- **Smart Issue Labeling**: Auto-classify and label issues based on repository rules
- **Issue Assignment**: Route issues to the right owners based on area mapping
- **Multi-Channel Notifications**: Send reports via Teams adaptive cards, personal messages, or email

## How It Works

### Agent-Based Workflow (IssueLens Agent)

1. **Scheduled Analysis**: GitHub Workflows run on schedule (e.g., daily at 00:00 UTC)
2. **Agent Execution**: The workflow invokes the **IssueLens Agent** using the GitHub Copilot CLI
3. **Issue Triage**: The agent scans for issues in target repositories and filters them based on critical issue criteria
4. **Notification**: Results are sent to configured webhook URLs (Teams, Logic Apps)

### Skills-Based Workflow

1. **Scheduled/Manual Trigger**: Workflow runs on schedule or manual dispatch
2. **Copilot CLI Execution**: Runs with `--no-custom-instructions` to use skills directly
3. **Skill Orchestration**: Copilot CLI invokes skills like `label-issue`, `check-sla`, `send-email`
4. **Notifications**: Personal notifications to assignees, summary emails to team

## Components

### 1. IssueLens Agent (`.github/agents/issuelens.agent.md`)

The core triage agent that identifies critical issues based on:

**Critical Issue Criteria:**
- **Hot Issues**: Multiple reports of same symptom, significant user engagement
- **Blocking Issues**: Core functionality broken with no workaround
- **Regression Issues**: Features broken that worked in previous releases

### 2. Skills (`.github/skills/`)

Modular capabilities that can be used by agents or invoked directly:

| Skill | Description |
|-------|-------------|
| `label-issue` | Classify and label issues based on repository-specific rules |
| `check-sla` | Check SLA compliance and generate status reports |
| `assign-issue` | Assign issues to owners based on area mapping |
| `find-critical-issues` | Identify hot/blocking/regression issues |
| `send-email` | Send HTML emails via Azure Logic App |
| `send-notification` | Send Teams adaptive card notifications |
| `send-personal-notification` | Send personal Teams messages to individuals |

### 3. Workflows (`.github/workflows/`)

| Workflow | Target | Mode |
|----------|--------|------|
| `issueLens-run.yml` | Java Tooling repos | Agent-based |
| `issueLens-jetbrains.yml` | JetBrains Copilot feedback | Agent-based |
| `issueLens-eclipse.yml` | Eclipse Copilot feedback | Agent-based |
| `issueLens-xcode.yml` | Xcode Copilot feedback | Agent-based |
| `triage-run-jetbrains.yml` | JetBrains Copilot feedback | Skills-based |

### 4. Notification Action (`.github/actions/notification/action.yml`)

Composite GitHub Action that sends JSON payloads to external endpoints (Logic Apps, webhooks).

## Setup & Configuration

### GitHub Secrets

Configure the following secrets in your repository:

| Secret | Description |
|--------|-------------|
| `PAT` | Personal Access Token for Copilot CLI |
| `GH_PAT` | GitHub PAT with repo permissions (for labeling, etc.) |
| `NOTIFICATION_URL` | Teams notification Logic App URL |
| `PERSONAL_NOTIFICATION_URL` | Personal notification Logic App URL |
| `MAILING_URL` | Email sending Logic App URL |
| `IDS` | JSON mapping of GitHub IDs to email addresses |
| `REPORT_RECIPIENTS` | Email addresses for summary reports |

### Repository Configuration

Skills can read repository-specific configuration files:

- `.github/sla.md` - SLA criteria for the repository
- `.github/label-instructions.md` - Labeling rules and available labels
- `.github/area_owners.md` - Technical area to owner mapping

## Target Repositories (Example)

**Java Tooling:**
- `microsoft/vscode-java-pack`
- `redhat-developer/vscode-java`
- `eclipse-jdtls/eclipse.jdt.ls`
- `microsoft/vscode-java-debug`
- `microsoft/vscode-java-test`
- `microsoft/vscode-gradle`
- `microsoft/vscode-maven`

**JetBrains Copilot:**
- `microsoft/copilot-intellij-feedback`

## License

MIT
