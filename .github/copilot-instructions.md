# JSON schema for IssueLens summary
- The critical output of custom agents defined at [agents/issuelens.agent.md](agents/issuelens.agent.md) is a JSON summary of triaged issues.
- This JSON output is consumed by the notification action defined at [actions/notification/action.yml](actions/notification/action.yml). The action actually sends the JSON payload to a configured URL which is a logic app HTTP trigger in the current setup.
- Keep the JSON schema defined in [agents/issuelens.agent.md](agents/issuelens.agent.md) and the logic app definition [../logicApp/triage-notification.logicapp.json](../logicApp/triage-notification.logicapp.json) in sync when making changes.
- When the JSON schema gets changed, make sure to update actions definition and logic app definition accordingly.
- When the JSON schema is updated, also update the example JSON output defined at [agents/issuelens.agent.md](agents/issuelens.agent.md).