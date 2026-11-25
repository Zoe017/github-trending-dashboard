# Entity relationship diagram

```mermaid
erDiagram
    LANGUAGE ||--o{ REPOSITORY : "primary language, nullable FK"
    REPOSITORY ||--o{ REPO_SNAPSHOT : "appears in"
    SNAPSHOT ||--|{ REPO_SNAPSHOT : "captures"
    REPO_SNAPSHOT ||--o{ SNAPSHOT_CONTRIBUTOR : "ranks"
    CONTRIBUTOR ||--o{ SNAPSHOT_CONTRIBUTOR : "appears in"

    LANGUAGE {
        INTEGER language_id PK
        TEXT name UK
    }
    REPOSITORY {
        INTEGER repo_id PK
        TEXT full_name UK
        TEXT owner_login
        TEXT name
        TEXT html_url
        TEXT description
        INTEGER language_id FK
        TEXT created_at
        TEXT first_seen_at
        TEXT last_seen_at
    }
    SNAPSHOT {
        INTEGER snapshot_id PK
        TEXT captured_at UK
        INTEGER window_days
        INTEGER repo_count
        TEXT source
    }
    REPO_SNAPSHOT {
        INTEGER snapshot_id PK, FK, UK "rank unique within snapshot"
        INTEGER repo_id PK, FK
        INTEGER rank UK "part of snapshot rank key"
        INTEGER stars
        INTEGER forks
        INTEGER open_issues
        INTEGER closed_issues
        INTEGER open_prs
        INTEGER closed_prs
    }
    CONTRIBUTOR {
        TEXT login PK
    }
    SNAPSHOT_CONTRIBUTOR {
        INTEGER snapshot_id PK, FK, UK "part of composite keys"
        INTEGER repo_id PK, FK, UK "part of composite keys"
        INTEGER position PK
        TEXT contributor_login FK, UK "unique within repo snapshot"
    }
```

| Relationship | Cardinality | Notes |
| --- | --- | --- |
| Language → Repository | One language to zero or more repositories | Each repository has zero or one detected primary language. The language FK is nullable. |
| Repository → Repo snapshot | One repository to zero or more observations | The associative entity resolves the many-to-many relationship between repositories and runs and holds the observed metrics. |
| Snapshot → Repo snapshot | One run to many observations when results exist | A successful empty search can produce a run with zero observations, as allowed by the schema. |
| Repo snapshot → Snapshot contributor | One observation to zero through five ranked contributors | The composite FK requires the repository to have appeared in that exact run. |
| Contributor → Snapshot contributor | One contributor to zero or more appearances | A login can appear for different repositories and runs. |

Composite constraints group the marked columns. `repo_snapshot` uses PK `(snapshot_id, repo_id)` and UK `(snapshot_id, rank)`. `snapshot_contributor` uses PK `(snapshot_id, repo_id, position)`, UK `(snapshot_id, repo_id, contributor_login)`, and FK `(snapshot_id, repo_id)`.

| Derived attribute | Rule | Location |
| --- | --- | --- |
| `health_status` | Green below 10 open issues, yellow from 10 through 50, red above 50. | `v_repo_snapshot_health` and matching live API logic |
| `star_gain` | Latest observed stars minus first observed stars for a repository. | `v_star_growth` |
| `health_score` | Rounded sum of equally weighted issue resolution and PR closure rates. An empty denominator gives a rate of 1. | `trending.py`, featured live API rows only |
