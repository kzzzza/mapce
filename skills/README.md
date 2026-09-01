# MAPCE Research Skills

This bundle turns MAPCE's MCP paper and code retrieval tools into a traceable
research workflow. It contains one routing skill and five specialist skills.

Install the complete bundle from a MAPCE installation:

```bash
mapce skills install --target codex
mapce skills install --target claude
mapce skills install --target agents
mapce skills install --path /custom/skill-directory
```

The skills call MAPCE through MCP. They do not open LanceDB directly and do not
start a second embedding service. Research notes and manuscripts live in the
user-approved project directory, outside MAPCE's database directory.

See `ATTRIBUTIONS.md` for the skills that informed this original implementation.
