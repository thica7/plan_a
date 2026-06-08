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

Allowed tool names must map to physical modules in `backend/packages/tools`.
Current structured tools are:

- `web_search`
- `robots_check`
- `fetch_page`
- `extract_facts`
- `find_official_docs`
- `search_review_site`
- `survey_simulator`
