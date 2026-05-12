"""Build a static GitHub Pages dashboard from the pipeline SQLite state."""
from __future__ import annotations

import argparse
import html
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def _connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _local_dt(value: str | None, tz: ZoneInfo) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def _today_bounds(tz: ZoneInfo) -> tuple[str, str]:
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(day=start.day)  # keep type checker calm
    end = start.fromtimestamp(start.timestamp() + 86400, tz)
    return (
        start.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
        end.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
    )


def _fetch_summary(conn: sqlite3.Connection | None, tz: ZoneInfo) -> dict[str, int]:
    if conn is None or not _has_table(conn, "publications"):
        return {"youtube_today": 0, "telegram_today": 0, "errors_today": 0}
    start, end = _today_bounds(tz)
    rows = conn.execute(
        """SELECT platform, status, COUNT(DISTINCT fingerprint) AS count
           FROM publications
           WHERE posted_at >= ? AND posted_at < ?
           GROUP BY platform, status""",
        (start, end),
    ).fetchall()
    summary = {"youtube_today": 0, "telegram_today": 0, "errors_today": 0}
    for row in rows:
        if row["platform"] == "youtube" and row["status"] == "ok":
            summary["youtube_today"] = int(row["count"])
        if row["platform"] == "telegram" and row["status"] == "ok":
            summary["telegram_today"] = int(row["count"])
        if row["status"] == "error":
            summary["errors_today"] += int(row["count"])
    return summary


def _latest_posts(conn: sqlite3.Connection | None) -> list[sqlite3.Row]:
    if conn is None or not _has_table(conn, "publications"):
        return []
    return conn.execute(
        """SELECT
               p.posted_at,
               p.platform,
               p.remote_id,
               p.status,
               p.error,
               p.fingerprint,
               COALESCE(f.title, s.title, p.fingerprint) AS title,
               COALESCE(f.source_id, s.source_id, '') AS source_id,
               COALESCE(f.category, '') AS category,
               m.view_count,
               m.like_count,
               m.comment_count
           FROM publications p
           LEFT JOIN item_features f ON f.fingerprint = p.fingerprint
           LEFT JOIN seen_items s ON s.fingerprint = p.fingerprint
           LEFT JOIN youtube_metrics m
             ON p.platform = 'youtube' AND m.video_id = p.remote_id
           ORDER BY p.posted_at DESC
           LIMIT 40"""
    ).fetchall()


def _candidate_scores(conn: sqlite3.Connection | None) -> list[sqlite3.Row]:
    if conn is None or not _has_table(conn, "candidate_scores"):
        return []
    return conn.execute(
        """SELECT run_at, stage, rank, source_id, category, title, score, reason, selected
           FROM candidate_scores
           ORDER BY run_at DESC, rank ASC
           LIMIT 60"""
    ).fetchall()


def _top_posts(conn: sqlite3.Connection | None) -> list[sqlite3.Row]:
    if conn is None or not _has_table(conn, "youtube_metrics"):
        return []
    return conn.execute(
        """SELECT
               m.video_id,
               m.view_count,
               m.like_count,
               m.comment_count,
               m.collected_at,
               COALESCE(f.title, s.title, m.fingerprint) AS title,
               COALESCE(f.source_id, s.source_id, '') AS source_id,
               COALESCE(f.category, '') AS category
           FROM youtube_metrics m
           LEFT JOIN item_features f ON f.fingerprint = m.fingerprint
           LEFT JOIN seen_items s ON s.fingerprint = m.fingerprint
           ORDER BY m.view_count DESC
           LIMIT 20"""
    ).fetchall()


def _status_badge(status: str) -> str:
    cls = "ok" if status in {"ok", "success"} else "bad"
    return f'<span class="badge {cls}">{html.escape(status)}</span>'


def _youtube_link(remote_id: str | None) -> str:
    if not remote_id:
        return "-"
    esc = html.escape(remote_id)
    return f'<a href="https://youtube.com/shorts/{esc}">{esc}</a>'


def _row_class(selected: int | str | None) -> str:
    return "selected" if str(selected) == "1" else ""


def build_dashboard(
    db_path: Path,
    out_dir: Path,
    timezone_name: str,
    *,
    workflow_name: str = "",
    workflow_conclusion: str = "",
    workflow_url: str = "",
) -> None:
    tz = ZoneInfo(timezone_name)
    conn = _connect(db_path)
    summary = _fetch_summary(conn, tz)
    latest = _latest_posts(conn)
    candidates = _candidate_scores(conn)
    top_posts = _top_posts(conn)
    updated = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    workflow_status = workflow_conclusion or "unknown"
    workflow_label = workflow_name or "unknown"
    workflow_link = (
        f'<a href="{html.escape(workflow_url)}">{html.escape(workflow_label)}</a>'
        if workflow_url
        else html.escape(workflow_label)
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "index.html"
    html_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="120">
  <title>LCB Mobile Dashboard</title>
  <style>
    :root {{
      --bg: #f4f0e8;
      --ink: #1f2430;
      --muted: #6e7480;
      --line: #d8d1c5;
      --ok: #147a49;
      --bad: #aa2e25;
      --accent: #0f5b78;
      --paper: #fffaf1;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at top left, #fff8e6, var(--bg) 42%, #e8eef1);
      color: var(--ink);
      font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 18px 60px; }}
    header {{ display: flex; justify-content: space-between; gap: 20px; align-items: end; margin-bottom: 24px; }}
    h1 {{ margin: 0; font-size: clamp(28px, 4vw, 48px); letter-spacing: 0; }}
    h2 {{ margin: 30px 0 12px; font-size: 20px; }}
    .muted {{ color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .card {{
      background: color-mix(in srgb, var(--paper) 92%, white);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 12px 30px rgb(31 36 48 / 0.08);
    }}
    .metric {{ font-size: 34px; font-weight: 750; margin-top: 8px; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--paper); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; background: #f7efe1; }}
    tr:last-child td {{ border-bottom: 0; }}
    tr.selected td {{ background: #e7f2ed; }}
    a {{ color: var(--accent); text-decoration-thickness: 1px; }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 700; }}
    .badge.ok {{ background: #dff3e8; color: var(--ok); }}
    .badge.bad {{ background: #ffe1dc; color: var(--bad); }}
    .tiny {{ font-size: 12px; color: var(--muted); }}
    .reason {{ max-width: 360px; color: var(--muted); }}
    @media (max-width: 860px) {{
      header {{ display: block; }}
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      table {{ font-size: 13px; }}
      th, td {{ padding: 8px; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>LCB Mobile Dashboard</h1>
      <div class="muted">Updated {html.escape(updated)}. Auto-refreshes every 2 minutes.</div>
    </div>
    <div class="muted">Source: <code>{html.escape(str(db_path))}</code></div>
  </header>

  <section class="grid">
    <div class="card"><div class="muted">YouTube posts today</div><div class="metric">{summary["youtube_today"]}/3</div></div>
    <div class="card"><div class="muted">Telegram posts today</div><div class="metric">{summary["telegram_today"]}</div></div>
    <div class="card"><div class="muted">Errors today</div><div class="metric">{summary["errors_today"]}</div></div>
    <div class="card"><div class="muted">Analytics samples</div><div class="metric">{len(top_posts)}</div></div>
    <div class="card"><div class="muted">Last workflow</div><div class="metric">{_status_badge(workflow_status)}</div><div class="tiny">{workflow_link}</div></div>
  </section>

  <h2>Latest Publications</h2>
  <table>
    <thead><tr><th>Time</th><th>Platform</th><th>Status</th><th>Video</th><th>Title</th><th>Views</th><th>Error</th></tr></thead>
    <tbody>
      {''.join(
          f'<tr><td>{_local_dt(row["posted_at"], tz)}</td>'
          f'<td>{html.escape(str(row["platform"]))}</td>'
          f'<td>{_status_badge(str(row["status"]))}</td>'
          f'<td>{_youtube_link(row["remote_id"]) if row["platform"] == "youtube" else html.escape(str(row["remote_id"] or "-"))}</td>'
          f'<td>{html.escape(str(row["title"]))}<div class="tiny">{html.escape(str(row["source_id"]))} {html.escape(str(row["category"]))}</div></td>'
          f'<td>{html.escape(str(row["view_count"] or "-"))}</td>'
          f'<td class="tiny">{html.escape(str(row["error"] or ""))}</td></tr>'
          for row in latest
      ) or '<tr><td colspan="7" class="muted">No publications yet.</td></tr>'}
    </tbody>
  </table>

  <h2>Candidate Selection Tests</h2>
  <table>
    <thead><tr><th>Run</th><th>Stage</th><th>Rank</th><th>Selected</th><th>Score</th><th>Title</th><th>Reason</th></tr></thead>
    <tbody>
      {''.join(
          f'<tr class="{_row_class(row["selected"])}"><td>{_local_dt(row["run_at"], tz)}</td>'
          f'<td>{html.escape(str(row["stage"]))}</td>'
          f'<td>{html.escape(str(row["rank"]))}</td>'
          f'<td>{"yes" if row["selected"] else ""}</td>'
          f'<td>{float(row["score"]):.2f}</td>'
          f'<td>{html.escape(str(row["title"]))}<div class="tiny">{html.escape(str(row["source_id"]))} {html.escape(str(row["category"]))}</div></td>'
          f'<td class="reason">{html.escape(str(row["reason"]))}</td></tr>'
          for row in candidates
      ) or '<tr><td colspan="7" class="muted">No candidate scores yet.</td></tr>'}
    </tbody>
  </table>

  <h2>Top YouTube Posts</h2>
  <table>
    <thead><tr><th>Video</th><th>Views</th><th>Likes</th><th>Comments</th><th>Title</th><th>Collected</th></tr></thead>
    <tbody>
      {''.join(
          f'<tr><td>{_youtube_link(row["video_id"])}</td>'
          f'<td>{html.escape(str(row["view_count"]))}</td>'
          f'<td>{html.escape(str(row["like_count"]))}</td>'
          f'<td>{html.escape(str(row["comment_count"]))}</td>'
          f'<td>{html.escape(str(row["title"]))}<div class="tiny">{html.escape(str(row["source_id"]))} {html.escape(str(row["category"]))}</div></td>'
          f'<td>{_local_dt(row["collected_at"], tz)}</td></tr>'
          for row in top_posts
      ) or '<tr><td colspan="6" class="muted">No YouTube metrics yet.</td></tr>'}
    </tbody>
  </table>

  <h2>Voice Test Logic</h2>
  <div class="card">
    <p>Voice tests should compare <b>lift over expected performance</b>, not raw views. The news topic already changes expected views, so a voice wins only if it repeatedly beats the analytics prediction for similar sources, categories and headline patterns.</p>
    <p class="muted">Next implementation step: assign voice variants randomly but evenly, store the variant per post, then show average residual views per voice here.</p>
  </div>
</main>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/state.db"))
    parser.add_argument("--out", type=Path, default=Path("site"))
    parser.add_argument("--timezone", default="America/Sao_Paulo")
    parser.add_argument("--workflow-name", default="")
    parser.add_argument("--workflow-conclusion", default="")
    parser.add_argument("--workflow-url", default="")
    args = parser.parse_args()
    build_dashboard(
        args.db,
        args.out,
        args.timezone,
        workflow_name=args.workflow_name,
        workflow_conclusion=args.workflow_conclusion,
        workflow_url=args.workflow_url,
    )


if __name__ == "__main__":
    main()
