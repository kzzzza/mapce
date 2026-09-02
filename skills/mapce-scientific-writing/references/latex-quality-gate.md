# LaTeX Layout Quality Gate

Apply this gate to every LaTeX document produced or revised by a MAPCE research Skill.
It keeps scientific/evidence review separate from mechanical layout approval.

## Build and log preflight

Run after every LaTeX generation or revision:

```bash
python <skill-dir>/scripts/latex_quality_gate.py build \
  --workspace <workspace> --tex manuscript/review.tex
```

The default overfull tolerance is 2 pt. A compile error, unresolved citation/reference,
or overfull box larger than 2 pt fails the gate. Do not suppress, crop, or scale away a
warning without checking that the resulting table, figure, equation, and text remain
readable.

The build stays under `build/latex-quality/`. A candidate PDF in that directory is not a
layout-approved deliverable.

## When visual review is required

The script renders every page when any of these conditions holds:

- `--final` is supplied for final delivery;
- a table or figure was added or changed since the last approved PDF;
- the page count changed since the last approved PDF;
- `--force-visual` is supplied.

For final delivery, always run the build again with `--final`. Inspect every PNG listed
under `visual_review.pages` with an image-viewing tool. Check text overlap, clipping,
column and margin violations, unreadable tables, displaced floats, equations, captions,
headers, footers, page numbers, links, references, and unexpected blank space.

Do not mark visual review as passed merely because compilation succeeded or because the
log has no overfull warning. If image inspection is unavailable, leave the status as
`visual_pending` and request human review.

## Record the visual decision

After inspecting every rendered page, record a pass:

```bash
python <skill-dir>/scripts/latex_quality_gate.py review \
  --workspace <workspace> --tex manuscript/review.tex \
  --result pass --reviewed-pages all \
  --notes "Checked every page for overlap, clipping, floats, equations, and references."
```

Only this command publishes the candidate as `manuscript/review.pdf` and writes
`manuscript/review.layout-qa.json` with `status=layout_approved`.

When visual defects exist, record them instead:

```bash
python <skill-dir>/scripts/latex_quality_gate.py review \
  --workspace <workspace> --tex manuscript/review.tex \
  --result fail --reviewed-pages all \
  --issue "Page 3 table overlaps the right column"
```

Repair the LaTeX and rerun the build. Permit at most two automated repair-and-recheck
cycles after the initial visual inspection. After three failed visual inspections, stop
automatic repair and request human layout guidance.

Evidence verification, scientific review, and venue compliance remain separate gates.
A layout-approved PDF may still be a `DRAFT — NOT FOR SUBMISSION`.
