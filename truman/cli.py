import argparse
import functools
import html
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .prepare import DEFAULT_TITLES, prepare
from .report import STYLE, write_report
from .runner import run_pair
from .world import World


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer")
    return number


class ReportHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/":
            files = sorted(Path(self.directory).glob("*.html"), reverse=True)
            items = "".join(f'<p><a href="/{html.escape(p.name)}">{html.escape(p.stem)}</a></p>' for p in files)
            content = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Truman</title><style>{STYLE}</style></head><body><main><header><div class="eyebrow">TRUMAN / WIKIPEDIA LAB</div>
<h1>Does the agent notice?</h1><p class="subtle">Compare the same task against present-day and 2016 Wikipedia pages.</p></header>
<section class="card"><h2>Experiment reports</h2>{items or '<p>No reports yet. Prepare a corpus and run the demo or a model experiment using the README.</p>'}</section>
<footer>Reports are local. Scripted demonstrations are labeled and are not model evaluations.</footer></main></body></html>'''.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        path = Path(self.translate_path(self.path)).resolve()
        if not path.is_relative_to(Path(self.directory).resolve()) or path.suffix != ".html" or not path.is_file():
            self.send_error(404)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def parser():
    result = argparse.ArgumentParser(description="Truman: paired experiments with saved Wikipedia revisions.")
    sub = result.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="Download real reference and historical Wikipedia revisions")
    prep.add_argument("--output", type=Path, default=Path("data/wikipedia-2016"))
    prep.add_argument("--old-date", default="2016-09-16")
    prep.add_argument("--title", action="append", help="Repeat for a custom corpus; default: 10 related pages")
    prep.add_argument("--transport", choices=["urllib", "curl"], default="urllib")
    check = sub.add_parser("inspect", help="Verify hashes and list source revisions")
    check.add_argument("--bundle", type=Path, default=Path("data/wikipedia-2016"))
    mcp = sub.add_parser("mcp", help="Serve the local Wikipedia reader over stdio MCP")
    mcp.add_argument("--bundle", type=Path, required=True)
    mcp.add_argument("--condition", choices=["reference", "historical"], required=True)
    mcp.add_argument("--trace", type=Path, required=True)
    mcp.add_argument("--max-calls", type=positive, default=12)
    cc = sub.add_parser("claude", help="Use installed Claude Code with its existing subscription login")
    cc.add_argument("--bundle", type=Path, default=Path("data/wikipedia-2016"))
    cc.add_argument("--output", type=Path, default=Path("runs"))
    cc.add_argument("--reports", type=Path, default=Path("reports"))
    cc.add_argument("--task", choices=["monarch", "prime-minister", "france", "all"], default="monarch")
    cc.add_argument("--model", help="Optional override; otherwise use Claude Code's default")
    cc.add_argument("--repeats", type=positive, default=1)
    cc.add_argument("--seed", type=int, default=42)
    cc.add_argument("--seconds", type=positive, default=180)
    cc.add_argument("--max-turns", type=positive, default=6)
    cc.add_argument("--max-calls", type=positive, default=12)
    cc.add_argument("--follow-up", action="append", default=[], help="Send after each completed answer, in the same conversation; repeat for more turns")
    cc.add_argument("--condition", choices=["reference", "historical"], help="Run only this condition; default: both")
    for name, help_text in (("demo", "Run a scripted plumbing demonstration, with no API calls"),
                            ("run", "Run a real paired model experiment")):
        run = sub.add_parser(name, help=help_text)
        run.add_argument("--bundle", type=Path, default=Path("data/wikipedia-2016"))
        run.add_argument("--output", type=Path, default=Path("runs"))
        run.add_argument("--reports", type=Path, default=Path("reports"))
        run.add_argument("--task", choices=["monarch", "prime-minister", "france", "all"], default="monarch")
        run.add_argument("--repeats", type=positive, default=1)
        run.add_argument("--seed", type=int, default=42)
        run.add_argument("--as-of", help="Must match the reference snapshot date; defaults to that date")
        run.add_argument("--max-calls", type=positive, default=12)
        run.add_argument("--max-turns", type=positive, default=8)
        run.add_argument("--max-output-tokens", type=positive, default=2000)
        run.add_argument("--total-output-tokens", type=positive, default=8000)
        run.add_argument("--seconds", type=positive, default=180)
        if name == "run":
            run.add_argument("--provider", choices=["openai", "anthropic"], required=True)
            run.add_argument("--model", required=True)
    serve = sub.add_parser("serve", help="Serve local HTML reports (read-only)")
    serve.add_argument("--directory", type=Path, default=Path("reports"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=positive, default=8765)
    sub.add_parser("test", help="Run the offline test suite")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare":
            manifest = prepare(args.output, args.old_date, args.title or DEFAULT_TITLES, args.transport)
            print(f"Saved {args.output}: " + ", ".join(f"{len(w['pages'])} {key} pages" for key, w in manifest["worlds"].items()))
        elif args.command == "inspect":
            for condition in ("reference", "historical"):
                world = World(args.bundle, condition)
                print(f"{condition}: {len(world.pages)} pages, all hashes verified")
                for page in world.pages.values():
                    print(f"  {page['title']}: revision {page['revision_id']} ({page['revision_at']})")
        elif args.command == "mcp":
            from .mcp_server import serve
            serve(args.bundle, args.condition, args.trace, args.max_calls)
        elif args.command == "claude":
            from .claude_code import run_claude_pair
            batch, results = run_claude_pair(args.bundle, args.output, args.task, args.model,
                args.repeats, args.seed, args.seconds, args.max_turns, args.max_calls, args.follow_up, args.condition)
            report = write_report(results, batch.name, args.reports)
            print(f"Report: {report}\nTraces: {batch}")
            return 0 if results and all(r["status"] == "completed" for r in results) else 1
        elif args.command in ("run", "demo"):
            batch, results = run_pair(args.bundle, args.output,
                "scripted" if args.command == "demo" else args.provider,
                None if args.command == "demo" else args.model, args.task,
                repeats=args.repeats, seed=args.seed, as_of=args.as_of,
                max_calls=args.max_calls, max_turns=args.max_turns,
                max_output_tokens=args.max_output_tokens, total_output_tokens=args.total_output_tokens, seconds=args.seconds)
            report = write_report(results, batch.name, args.reports)
            print(f"Report: {report}\nTraces: {batch}")
            return 0 if results and all(r["status"] == "completed" for r in results) else 1
        elif args.command == "serve":
            directory = args.directory.resolve()
            if not directory.is_dir():
                raise ValueError(f"Report directory missing: {directory}. Run demo first.")
            handler = functools.partial(ReportHandler, directory=str(directory))
            server = ThreadingHTTPServer((args.host, args.port), handler)
            print(f"Reports: http://{args.host}:{args.port}", flush=True)
            server.serve_forever()
        elif args.command == "test":
            import unittest
            suite = unittest.defaultTestLoader.discover("tests")
            return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
