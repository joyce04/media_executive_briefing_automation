# One shared SQLite DB for all Organizations, but separate LangGraph checkpoint files per Organization

The platform is multi-tenant: many Organizations share one deployment. There are two pieces of state to place: the **pipeline data** (articles, analyses, briefings, story continuity) and the **LangGraph checkpoint state** (resumability for in-flight runs). We picked different placements for each.

## Decision

- **Pipeline data**: a single SQLite database at `data/media_intel.db`. Every pipeline table carries an `org_id` column and every repository function filters by it.
- **LangGraph checkpoints**: one SQLite file per Organization at `data/checkpoints/{org_slug}.db`, opened by `AsyncSqliteSaver` for the duration of the run.

## Why this is worth recording

The conventional answer for a multi-tenant pipeline is one of two extremes: a shared DB for everything (operationally simple, isolation by convention) or DB-per-tenant for everything (strong isolation, more operations). We did a split, which is the kind of decision a future reader will look at and try to "fix" toward one of the extremes.

## Why the split

- **Shared pipeline DB** is fine because the data is queried with `org_id` filters that the repositories enforce, the volume is modest (one Organization produces dozens of articles a day, not millions), and cross-Organization queries (e.g. "global pipeline health") are easier with shared storage.
- **Per-Organization checkpoint files** is necessary because `AsyncSqliteSaver` opens an exclusive SQLite connection for the lifetime of `ainvoke()`. If two Organizations' runs overlap on the same checkpoint file, they contend on the same SQLite writer. Splitting the files removes that contention entirely and isolates checkpoint corruption to one Organization if it happens.

## Considered alternatives

- **Everything in one DB, checkpoints in a `checkpoints` table within `media_intel.db`.** Rejected: `AsyncSqliteSaver` expects ownership of a database, and the checkpoint table schema is library-managed.
- **DB-per-Organization for everything.** Rejected: complicates cross-Organization observability, multiplies migration work, and isn't justified by the data volumes we expect.

## Consequences

- The `org_id` filter is an invariant — **every** query on a pipeline table must include it. Repository methods are the enforcement layer.
- Onboarding an Organization requires creating its checkpoint file at first run; this is handled implicitly by `AsyncSqliteSaver.from_conn_string()`.
- Backup / restore is two artifacts: the main DB plus the `checkpoints/` directory.
