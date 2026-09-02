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

At research intake, the agent asks whether paper indexing is authorized for the
current project or requires approval for each paper. Missing or unattended input
defaults to per-paper approval; external-search permission alone never authorizes
a write to MAPCE.

Every LaTeX change uses the bundled compile and log gate. Final delivery, table or
figure changes, and page-count changes also require inspection of every rendered page.
Only a visually reviewed PDF receives a `layout_approved` record.

See `ATTRIBUTIONS.md` for the skills that informed this original implementation.
