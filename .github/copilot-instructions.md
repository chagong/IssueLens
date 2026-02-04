# IssueLens Project Instructions

## Overview
IssueLens is a GitHub Copilot-powered issue triage system with custom agents and skills.

## Project Structure

### Agents
- [agents/issuelens.agent.md](agents/issuelens.agent.md) - Main triage agent for identifying critical issues

### Skills
Skills are modular capabilities that can be used by agents or invoked directly:

- **label-issue** - Classify and label GitHub issues based on repository-specific instructions
- **check-sla** - Check SLA compliance status for GitHub issues
- **assign-issue** - Assign issues to the right person based on area ownership
- **find-critical-issues** - Triage issues and identify critical ones (hot/blocking/regression)
- **send-email** - Send HTML email notifications via Azure Logic App
- **send-notification** - Send adaptive card notifications to Teams
- **send-personal-notification** - Send personal workflow bot messages to Teams

### Workflows
- `issueLens-run.yml` - Main daily triage for Java Tooling repositories
- `issueLens-jetbrains.yml` - Triage for JetBrains Copilot feedback
- `issueLens-eclipse.yml` - Triage for Eclipse Copilot feedback
- `issueLens-xcode.yml` - Triage for Xcode Copilot feedback
- `triage-run-jetbrains.yml` - Skills-based triage workflow (uses Copilot CLI directly with skills)

## JSON Schema for IssueLens Summary
- The critical output of custom agents defined at [agents/issuelens.agent.md](agents/issuelens.agent.md) is a JSON summary of triaged issues.
- This JSON output is consumed by the notification action defined at [actions/notification/action.yml](actions/notification/action.yml). The action sends the JSON payload to a configured URL (Logic App HTTP trigger).
- Keep the JSON schema defined in [agents/issuelens.agent.md](agents/issuelens.agent.md) and the logic app definition [../logicApp/triage-notification.logicapp.json](../logicApp/triage-notification.logicapp.json) in sync when making changes.
- When the JSON schema gets changed, make sure to update actions definition and logic app definition accordingly.
- When the JSON schema is updated, also update the example JSON output defined at [agents/issuelens.agent.md](agents/issuelens.agent.md).

## Skills Development Guidelines
- Each skill is defined in `.github/skills/<skill-name>/SKILL.md`
- Skills should have clear input/output specifications
- Reference templates and schemas should be in `references/` subdirectory
- Skills can read repository-specific configuration files (e.g., `.github/sla.md`, `.github/label-instructions.md`)