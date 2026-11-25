# Data dictionary

The database uses SQLite. The default path is `trending.db` and `TRENDING_DB` overrides it. Timestamps use ISO-8601 text. Every connection enables foreign-key enforcement with `PRAGMA foreign_keys = ON`.

## language

One lookup row per detected primary programming language.

| Column | Type | Null | Constraints | Description |
| --- | --- | --- | --- | --- |
| `language_id` | INTEGER | No | PK | Local identifier used by repository rows. |
| `name` | TEXT | No | UNIQUE | Primary language label reported by GitHub. |

## repository

One row per GitHub repository, with the latest known descriptive attributes.

| Column | Type | Null | Constraints | Description |
| --- | --- | --- | --- | --- |
| `repo_id` | INTEGER | No | PK | GitHub's numeric repository ID preserves identity across renames or transfers. |
| `full_name` | TEXT | No | UNIQUE, CHECK matches owner and name | Current repository path in owner/name form. |
| `owner_login` | TEXT | No | Part of full-name CHECK | Current owner handle. |
| `name` | TEXT | No | Part of full-name CHECK | Repo name within the owner's account. |
| `html_url` | TEXT | No | Required | Browser link to the repository. |
| `description` | TEXT | Yes | Optional | GitHub's repository description when supplied. |
| `language_id` | INTEGER | Yes | FK to `language` | Primary detected language. NULL means the search item supplied none. |
| `created_at` | TEXT | No | Required | GitHub creation time used to select eligible repos. |
| `first_seen_at` | TEXT | No | Used in last-seen CHECK | Capture timestamp at initial insert. Upserts preserve this value. |
| `last_seen_at` | TEXT | No | CHECK ≥ first_seen_at | Most recent capture timestamp this repository appeared in. |

## snapshot

One row per successfully persisted collection run.

| Column | Type | Null | Constraints | Description |
| --- | --- | --- | --- | --- |
| `snapshot_id` | INTEGER | No | PK | Local identifier for one collection run. |
| `captured_at` | TEXT | No | UNIQUE | Capture time for the run. Issue, PR, and contributor values may reflect the existing web cache. |
| `window_days` | INTEGER | No | CHECK > 0 | Age window for repository creation in the search. |
| `repo_count` | INTEGER | No | CHECK ≥ 0 | Number of distinct repositories included in the run. |
| `source` | TEXT | No | CHECK IN ('cli', 'web') | `cli` identifies a scheduled or manual command. `web` identifies a fresh dashboard refresh. |

## repo_snapshot

One row per repository per snapshot, with ranks and measured counts.

| Column | Type | Null | Constraints | Description |
| --- | --- | --- | --- | --- |
| `snapshot_id` | INTEGER | No | Composite PK, FK to `snapshot`, part of rank UNIQUE | Run containing the observation. Deleting that run cascades here. |
| `repo_id` | INTEGER | No | Composite PK, FK to `repository` | Stable repository identity for the observation. |
| `rank` | INTEGER | No | CHECK ≥ 1, UNIQUE with snapshot_id | One-based position after deduplication. |
| `stars` | INTEGER | No | CHECK ≥ 0 | Total stargazers at observation. |
| `forks` | INTEGER | No | CHECK ≥ 0 | Total forks at observation. Ingestion supplies zero if the field is absent. |
| `open_issues` | INTEGER | No | CHECK ≥ 0 | Open issues counted separately from pull requests. |
| `closed_issues` | INTEGER | No | CHECK ≥ 0 | Closed issues counted separately from pull requests. |
| `open_prs` | INTEGER | No | CHECK ≥ 0 | Open pull requests. |
| `closed_prs` | INTEGER | No | CHECK ≥ 0 | Pull requests in either the closed or merged state. |

## contributor

One lookup row per GitHub login that has appeared among the top contributors.

| Column | Type | Null | Constraints | Description |
| --- | --- | --- | --- | --- |
| `login` | TEXT | No in the writer | PK | GitHub handle supplied by the contributors endpoint. SQLite permits NULL in this exact TEXT PK declaration, while the referencing column requires a value. |

## snapshot_contributor

One ranked contributor for a particular repository observation.

| Column | Type | Null | Constraints | Description |
| --- | --- | --- | --- | --- |
| `snapshot_id` | INTEGER | No | Composite PK, FK, and UNIQUE | Run in which the contributor appeared. |
| `repo_id` | INTEGER | No | Composite PK, FK, and UNIQUE | Together with snapshot_id, identifies the observation. Deleting the observation cascades here. |
| `position` | INTEGER | No | Composite PK, CHECK 1–5 | One-based contributor ranking returned by GitHub. |
| `contributor_login` | TEXT | No | FK to `contributor`, UNIQUE with snapshot_id and repo_id | Contributor handle. Each handle appears at most once per observed repo. |

## Views

| View | Grain | Purpose |
| --- | --- | --- |
| `v_repo_snapshot_health` | One row per repository per snapshot | Join observations to repository details and derive health status. |
| `v_latest_trending` | One row per repository in the highest-ID snapshot | Report the latest inserted ranking. |
| `v_star_growth` | One row per observed repository | Compare first and latest captured star counts and count appearances. |
| `v_language_mix` | One row per snapshot and primary language label | Count repositories and total stars by language. Missing language appears as `(none)`. Historical groups use the latest stored language. |

## Business rules

- Open issues below 10 are green. Counts 10 through 50 are yellow. Counts above 50 are red.
- Across search pages, the first occurrence of each repository ID retains its rank order. The database allows one row per repository per snapshot and one repository per rank.
- Every snapshot, including related dimensions and contributor positions, is written in one transaction. A failed write rolls back the full batch.
- A negative star gain is possible because a user can remove a star. Star counts themselves must be nonnegative.
