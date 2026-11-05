"""RoomBrain command line interface (stdlib only)."""

import argparse
import http.server
import sys
import threading

HEALTH_BODY = b'{"status":"ok"}'
DEFAULT_HEALTH_PORT = 8000


class HealthHandler(http.server.BaseHTTPRequestHandler):
    """Serve GET /health with a byte-exact JSON body."""

    def do_GET(self):
        if self.path == "/health":
            body = HEALTH_BODY
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def build_parser():
    parser = argparse.ArgumentParser(
        prog="roombrain",
        description="RoomBrain walking skeleton CLI.",
    )
    sub = parser.add_subparsers(title="commands", dest="command")
    p_register = sub.add_parser(
        "register",
        help="Register this agent with the Switch (reserved for a later lap).",
    )
    p_register.set_defaults(func=cmd_register)
    p_run = sub.add_parser(
        "run",
        help="Run the agent loop (echo mode in the skeleton).",
    )
    p_run.add_argument(
        "--echo",
        action="store_true",
        help="Run the stdin echo loop with a health server.",
    )
    p_run.add_argument(
        "--health-port",
        type=int,
        default=DEFAULT_HEALTH_PORT,
        help="Port for the health endpoint (default: %(default)s).",
    )
    p_run.set_defaults(func=cmd_run)
    p_seed = sub.add_parser(
        "seed-demo",
        help="Seed demo data (reserved for a later lap).",
    )
    p_seed.set_defaults(func=cmd_seed_demo)
    return parser


def cmd_register(args):
    print("register: reserved for a later lap (no Switch client yet).")
    return 0


def cmd_seed_demo(args):
    print("seed-demo: reserved for a later lap (no demo data yet).")
    return 0


def cmd_run(args):
    if args.echo:
        return run_echo(args.health_port)
    print("run: pass --echo for the skeleton echo loop.")
    return 0


def format_echo_line(line):
    return "echo: " + line.strip()


def run_echo(health_port):
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", health_port), HealthHandler
    )
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for line in sys.stdin:
            if line.strip():
                print(format_echo_line(line), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)
