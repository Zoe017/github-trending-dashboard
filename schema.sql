-- GitHub Trending Dashboard — SQLite schema
--
-- Design principle: separate what a repository IS (stable attributes)
-- from what it MEASURES at a point in time (metrics that change).
--
--   language ─1:N─ repository ─1:N─ repo_snapshot ─N:1─ snapshot
--                                         │
--                                        1:N
--                                         │
--                               snapshot_contributor ─N:1─ contributor
--
-- SQLite does not enforce foreign keys unless each connection runs
-- PRAGMA foreign_keys = ON (db.connect() does this).

-- ---------------------------------------------------------------------
-- Lookup table: one row per programming language name.
-- Normalized out of repository so "Python" is stored once and spelled
-- consistently, and so language-level reporting is a simple GROUP BY.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS language (
    language_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------
-- One row per GitHub repository. Stable attributes only.
-- repo_id is GitHub's own numeric id (stable even if the repo is renamed);
-- full_name ("owner/name") can change, so it is UNIQUE but not the PK.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS repository (
    repo_id       INTEGER PRIMARY KEY,               -- GitHub repository id
    full_name     TEXT    NOT NULL UNIQUE,           -- "owner/name"
    owner_login   TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    html_url      TEXT    NOT NULL,
    description   TEXT,                              -- GitHub allows empty descriptions
    language_id   INTEGER REFERENCES language(language_id),  -- NULL = no detected language
    created_at    TEXT    NOT NULL,                  -- ISO-8601, from GitHub
    first_seen_at TEXT    NOT NULL,                  -- when this pipeline first saw it
    last_seen_at  TEXT    NOT NULL,
    CHECK (full_name = owner_login || '/' || name),
    CHECK (last_seen_at >= first_seen_at)
);

-- ---------------------------------------------------------------------
-- One row per pipeline run ("a photo of the trending list").
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_id  INTEGER PRIMARY KEY,
    captured_at  TEXT    NOT NULL UNIQUE,            -- ISO-8601 timestamp of the run
    window_days  INTEGER NOT NULL CHECK (window_days > 0),  -- "created in last N days"
    repo_count   INTEGER NOT NULL CHECK (repo_count >= 0),
    source       TEXT    NOT NULL CHECK (source IN ('cli', 'web'))
);

-- ---------------------------------------------------------------------
-- Associative entity between repository and snapshot (M:N), carrying
-- the time-varying metrics. Composite PK: a repo appears at most once
-- per snapshot.
--
-- health_status is NOT stored: it is derived from open_issues in the
-- views below, so it can never disagree with open_issues.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS repo_snapshot (
    snapshot_id   INTEGER NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    repo_id       INTEGER NOT NULL REFERENCES repository(repo_id),
    rank          INTEGER NOT NULL CHECK (rank >= 1),
    stars         INTEGER NOT NULL CHECK (stars >= 0),
    forks         INTEGER NOT NULL CHECK (forks >= 0),
    open_issues   INTEGER NOT NULL CHECK (open_issues >= 0),
    closed_issues INTEGER NOT NULL CHECK (closed_issues >= 0),
    open_prs      INTEGER NOT NULL CHECK (open_prs >= 0),
    closed_prs    INTEGER NOT NULL CHECK (closed_prs >= 0),
    PRIMARY KEY (snapshot_id, repo_id),
    UNIQUE (snapshot_id, rank)                       -- no two repos share a rank in one run
);

-- ---------------------------------------------------------------------
-- One row per GitHub user who has appeared as a top contributor.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contributor (
    login TEXT PRIMARY KEY
);

-- ---------------------------------------------------------------------
-- Top-N contributors of a repo *as of a snapshot* (rankings change over
-- time, so this hangs off repo_snapshot, not off repository).
-- Composite FK (snapshot_id, repo_id) -> repo_snapshot guarantees we
-- never record contributors for a repo that was not in that snapshot.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS snapshot_contributor (
    snapshot_id       INTEGER NOT NULL,
    repo_id           INTEGER NOT NULL,
    position          INTEGER NOT NULL CHECK (position BETWEEN 1 AND 5),
    contributor_login TEXT    NOT NULL REFERENCES contributor(login),
    PRIMARY KEY (snapshot_id, repo_id, position),
    UNIQUE (snapshot_id, repo_id, contributor_login),
    FOREIGN KEY (snapshot_id, repo_id)
        REFERENCES repo_snapshot(snapshot_id, repo_id) ON DELETE CASCADE
);

-- Supports "history of one repo" queries (the PK already covers snapshot-first lookups).
CREATE INDEX IF NOT EXISTS idx_repo_snapshot_repo ON repo_snapshot(repo_id, snapshot_id);

-- =====================================================================
-- Summary views (analytical layer). Business rules live here, once.
-- =====================================================================

-- Every repo row with its derived health status, for any snapshot.
CREATE VIEW IF NOT EXISTS v_repo_snapshot_health AS
SELECT
    s.snapshot_id,
    s.captured_at,
    rs.rank,
    r.repo_id,
    r.full_name,
    r.html_url,
    r.description,
    l.name AS language,
    rs.stars,
    rs.forks,
    rs.open_issues,
    rs.closed_issues,
    rs.open_prs,
    rs.closed_prs,
    CASE
        WHEN rs.open_issues < 10  THEN 'green'
        WHEN rs.open_issues <= 50 THEN 'yellow'
        ELSE 'red'
    END AS health_status
FROM repo_snapshot rs
JOIN snapshot   s ON s.snapshot_id = rs.snapshot_id
JOIN repository r ON r.repo_id     = rs.repo_id
LEFT JOIN language l ON l.language_id = r.language_id;   -- LEFT: language may be NULL

-- The most recent trending list.
CREATE VIEW IF NOT EXISTS v_latest_trending AS
SELECT *
FROM v_repo_snapshot_health
WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM snapshot);

-- Star growth per repo between its first and latest appearance.
CREATE VIEW IF NOT EXISTS v_star_growth AS
WITH ordered AS (
    SELECT
        rs.repo_id,
        s.captured_at,
        rs.stars,
        ROW_NUMBER() OVER (PARTITION BY rs.repo_id ORDER BY s.captured_at ASC)  AS rn_first,
        ROW_NUMBER() OVER (PARTITION BY rs.repo_id ORDER BY s.captured_at DESC) AS rn_last,
        COUNT(*)     OVER (PARTITION BY rs.repo_id)                             AS appearances
    FROM repo_snapshot rs
    JOIN snapshot s ON s.snapshot_id = rs.snapshot_id
)
SELECT
    r.full_name,
    f.captured_at                 AS first_captured_at,
    l.captured_at                 AS last_captured_at,
    f.stars                       AS first_stars,
    l.stars                       AS last_stars,
    l.stars - f.stars             AS star_gain,
    f.appearances
FROM ordered f
JOIN ordered l    ON l.repo_id = f.repo_id AND l.rn_last = 1
JOIN repository r ON r.repo_id = f.repo_id
WHERE f.rn_first = 1;

-- Language mix of each snapshot.
CREATE VIEW IF NOT EXISTS v_language_mix AS
SELECT
    s.snapshot_id,
    s.captured_at,
    COALESCE(l.name, '(none)') AS language,
    COUNT(*)                   AS repo_count,
    SUM(rs.stars)              AS total_stars
FROM repo_snapshot rs
JOIN snapshot   s ON s.snapshot_id = rs.snapshot_id
JOIN repository r ON r.repo_id     = rs.repo_id
LEFT JOIN language l ON l.language_id = r.language_id
GROUP BY s.snapshot_id, s.captured_at, COALESCE(l.name, '(none)');
