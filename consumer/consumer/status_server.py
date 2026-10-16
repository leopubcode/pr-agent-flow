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
        '<p class="empty text-center text-lg font-bold text-white bg-black/60 border-4 border-dashed '
        f'border-yellow-300 p-6 mt-8">No agents in <code>{html.escape(str(agent_file))}</code>.</p>'
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh_seconds}">
<title>Agent Status</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body {{
    font-family: "Comic Sans MS", "Comic Sans", "Chalkboard SE", cursive, monospace;
    background-color: #ff00ff;
    background-image:
      repeating-linear-gradient(45deg, #ff00ff 0px, #ff00ff 18px, #00ffff 18px, #00ffff 36px),
      repeating-linear-gradient(-45deg, rgba(255,255,0,0.35) 0px, rgba(255,255,0,0.35) 18px,
                                 rgba(0,255,0,0.35) 18px, rgba(0,255,0,0.35) 36px);
  }}
  .rainbow-text {{
    background-image: linear-gradient(90deg, #ff0000, #ff9900, #ffee00, #33ff00, #00ffee, #0066ff, #cc00ff, #ff0000);
    background-size: 200% auto;
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    animation: rainbow-move 4s linear infinite;
    text-shadow: 3px 3px 0 rgba(0,0,0,0.25);
  }}
  @keyframes rainbow-move {{ to {{ background-position: 200% center; }} }}
  .blink {{ animation: blink 1.1s steps(2, start) infinite; }}
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
  .bevel {{
    border-style: solid;
    border-width: 5px;
    border-color: #ffffff #4b4b4b #4b4b4b #ffffff;
    box-shadow: inset 2px 2px 0 rgba(255,255,255,.6), inset -2px -2px 0 rgba(0,0,0,.4), 5px 5px 0 #000;
  }}
  .marquee-bar {{ background: repeating-linear-gradient(90deg, #ffff00 0 20px, #000 20px 40px); color: #fff; }}
  .badge {{ font-weight:900; padding:2px 10px; border:3px solid #000; text-transform:uppercase;
           font-size:11px; letter-spacing:.5px; box-shadow:3px 3px 0 #000; }}
  .idle {{ background:#39ff14; color:#000; }}
  .working, .busy {{ background:#ffd400; color:#000; }}
  .error, .gone {{ background:#ff1744; color:#fff; }}
  .unknown {{ background:#d9d9d9; color:#000; }}
  pre {{ font-family: "Courier New", monospace; }}
</style>
</head>
<body class="min-h-screen px-4 py-6">
<marquee behavior="alternate" scrollamount="6"
         class="marquee-bar font-bold text-lg py-2 border-4 border-black mb-4">
  🚧🌟 WELCOME TO THE AGENT STATUS SUPERHIGHWAY 🌟🚧 — Best viewed in Netscape Navigator at 800x600
  — Sign the guestbook! 🚧
</marquee>
<main class="max-w-3xl mx-auto">
  <div class="bevel bg-gradient-to-br from-fuchsia-600 via-cyan-400 to-yellow-300 p-5 mb-6">
    <header class="flex justify-between items-baseline gap-3 flex-wrap">
      <div>
        <h1 class="rainbow-text text-4xl font-black tracking-tight">&#9733; Agent Status &#9733;</h1>
        <div class="text-sm font-bold text-white" style="text-shadow:1px 1px 0 #000">
          {len(rows)} agent(s) from <code class="bg-black text-lime-300 px-1">{html.escape(str(agent_file))}</code>
        </div>
      </div>
      <div class="text-sm font-bold text-white blink" style="text-shadow:1px 1px 0 #000">
        Updated {now} &middot; refreshes every {refresh_seconds}s
      </div>
    </header>
    <div class="mt-3 inline-block bg-yellow-300 border-4 border-black px-3 py-1 font-black text-black blink">
      &#9888; UNDER CONSTRUCTION &#9888;
    </div>
  </div>
  <div class="space-y-5">
{cards}
  </div>
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
    return f"""<section class="card bevel bg-white p-4">
  <h2 class="text-lg font-black flex items-center gap-2 flex-wrap">
    <span class="text-fuchsia-700">{e(record.pr_key)}</span>
    <span class="badge {css}">{e(label)}</span>
  </h2>
  <dl class="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 my-3 text-sm">
    <dt class="font-bold text-cyan-700">Pane</dt><dd><code class="bg-gray-100 px-1">{e(record.pane_id)}</code></dd>
    <dt class="font-bold text-cyan-700">Tab</dt><dd class="break-words">{e(record.tab_label)}</dd>
    <dt class="font-bold text-cyan-700">Sandbox</dt><dd class="break-words">{e(record.sandbox_name)}</dd>
  </dl>
  <pre class="bg-black text-lime-300 border-2 border-black p-3 overflow-x-auto text-xs">$ herdr agent get {e(record.pane_id)}
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
