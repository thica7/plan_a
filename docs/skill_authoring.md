# Skill Authoring

Create a new dimension by adding a YAML file under `backend/packages/skills`.

Required fields:

- `name`
- `description`
- `tools_allowlist`
- `query_templates`
- `max_turns`
- `source_type`
- `output.prefix`
- `output.required_dimension`

The registry validates each file with `SkillSpec` at application startup.

