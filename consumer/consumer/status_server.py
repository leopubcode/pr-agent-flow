"""Status page: one card per Coordinator in the agent file, showing `herdr agent get <pane>`.

Read-only. Runs `herdr agent get` for every line of `agents.tsv` on each page load and
shows its output as-is (pretty-printed when it is JSON), so it reflects exactly what herdr
reports. Stdlib only; bind to localhost unless you mean to expose it.
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agent_file import AgentFile, AgentRecord
from .config import agent_file_path, home_from_env

HERDR_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class HerdrResult:
    exit_code: int | None  # None when herdr could not be run at all
    output: str
    status: str | None  # `agent_status` from the JSON, when there is one


def herdr_agent_get(pane_id: str) -> HerdrResult:
    try:
        proc = subprocess.run(
            ["herdr", "agent", "get", pane_id], capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=HERDR_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return HerdrResult(None, f"herdr agent get timed out after {HERDR_TIMEOUT_SECONDS}s", None)
    except OSError as exc:
        return HerdrResult(None, f"could not run herdr: {exc}", None)
    output = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
    return HerdrResult(proc.returncode, _pretty(proc.stdout) or output, _agent_status(proc.stdout))


def _pretty(stdout: str) -> str | None:
    try:
        return json.dumps(json.loads(stdout), indent=2)
    except ValueError:
        return None


def _agent_status(stdout: str) -> str | None:
    """Same lookup as `HerdrSbxRuntime.get_agent_info`: `result.agent.agent_status`, leniently."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    result = data.get("result", data)
    agent = result.get("agent", result) if isinstance(result, dict) else {}
    status = agent.get("agent_status") if isinstance(agent, dict) else None
    return str(status) if status is not None else None


def render_page(rows: list[tuple[AgentRecord, HerdrResult]], agent_file: Path, refresh_seconds: int) -> str:
    cards = "\n".join(_render_card(record, result) for record, result in rows) or (
        f'<p class="empty">No agents in <code>{html.escape(str(agent_file))}</code>.</p>'
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh_seconds}">
<title>Agent Status</title>
<style>
:root {{ --bg:#f7f7f8; --card:#fff; --fg:#1d1d1f; --muted:#6b6b70; --border:#e2e2e6; --code:#f1f1f3;
        --ok:#1a7f37; --busy:#9a6700; --bad:#cf222e; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#111113; --card:#1b1b1f; --fg:#ececf0; --muted:#9a9aa2; --border:#2c2c32; --code:#141417;
          --ok:#3fb950; --busy:#d29922; --bad:#f85149; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif; }}
main {{ max-width:960px; margin:0 auto; padding:24px 16px; }}
header {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; flex-wrap:wrap; }}
h1 {{ font-size:20px; margin:0 0 4px; }}
.meta {{ color:var(--muted); font-size:13px; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; margin-top:16px; }}
.card h2 {{ font-size:16px; margin:0; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
dl {{ display:grid; grid-template-columns:max-content 1fr; gap:2px 12px; margin:10px 0; font-size:13px; }}
dt {{ color:var(--muted); }} dd {{ margin:0; overflow-wrap:anywhere; }}
pre {{ background:var(--code); border:1px solid var(--border); border-radius:6px; padding:10px;
      margin:0; overflow-x:auto; font-size:12.5px; }}
.badge {{ font-size:12px; font-weight:600; padding:1px 8px; border-radius:999px; border:1px solid currentColor; }}
.idle {{ color:var(--ok); }} .working, .busy {{ color:var(--busy); }} .error, .gone {{ color:var(--bad); }}
.unknown {{ color:var(--muted); }}
.empty {{ color:var(--muted); margin-top:24px; }}
</style>
</head>
<body>
<main>
<header>
  <div><h1>Agent Status</h1><div class="meta">{len(rows)} agent(s) from <code>{html.escape(str(agent_file))}</code></div></div>
  <div class="meta">Updated {now} · refreshes every {refresh_seconds}s</div>
</header>
{cards}
</main>
</body>
</html>
"""


def _render_card(record: AgentRecord, result: HerdrResult) -> str:
    if result.exit_code is None:
        label, css = "error", "error"
    elif result.exit_code != 0:
        label, css = f"gone (exit {result.exit_code})", "gone"
    else:
        label = result.status or "unknown"
        css = label.lower() if label.lower() in {"idle", "working", "busy"} else "unknown"
    e = html.escape
    return f"""<section class="card">
  <h2>{e(record.pr_key)} <span class="badge {css}">{e(label)}</span></h2>
  <dl>
    <dt>Pane</dt><dd><code>{e(record.pane_id)}</code></dd>
    <dt>Tab</dt><dd>{e(record.tab_label)}</dd>
    <dt>Sandbox</dt><dd>{e(record.sandbox_name)}</dd>
  </dl>
  <pre>$ herdr agent get {e(record.pane_id)}
{e(result.output) or "(no output)"}</pre>
</section>"""


def make_handler(agent_file: Path, refresh_seconds: int) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.split("?")[0] != "/":
                self.send_error(404)
                return
            records = AgentFile(agent_file).all()
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(herdr_agent_get, [r.pane_id for r in records]))
            body = render_page(list(zip(records, results)), agent_file, refresh_seconds).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a status page for the Coordinators in agents.tsv.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--refresh", type=int, default=5, help="page auto-refresh interval in seconds")
    args = parser.parse_args()

    agent_file = agent_file_path(home_from_env())
    server = ThreadingHTTPServer((args.host, args.port), make_handler(agent_file, args.refresh))
    print(f"Serving agent status for {agent_file} on http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
