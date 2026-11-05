"""RoomBrain command line interface (stdlib only)."""

import argparse
import http.server
import os
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
        help="Register this agent with the Switch (idempotent, persists to .env).",
    )
    p_register.add_argument(
        "--server",
        default=os.environ.get("SWITCH_SERVER_URL", "http://127.0.0.1:8000"),
        help="Switch server base URL (default: SWITCH_SERVER_URL or %(default)s).",
    )
    p_register.add_argument(
        "--token",
        default=os.environ.get("AGENT_REGISTRATION_TOKEN", ""),
        help="One-shot registration token (default: AGENT_REGISTRATION_TOKEN).",
    )
    p_register.add_argument(
        "--name",
        default="roombrain",
        help="Agent name to register (default: %(default)s).",
    )
    p_register.add_argument(
        "--env-file",
        default=".env",
        help="Env file for ROOMBRAIN_AGENT_ID/API_KEY (default: %(default)s).",
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
        "--server",
        default=os.environ.get("SWITCH_SERVER_URL", "http://127.0.0.1:8000"),
        help="Switch server base URL (default: SWITCH_SERVER_URL or %(default)s).",
    )
    p_run.add_argument(
        "--rooms",
        default=os.environ.get("ROOMBRAIN_ROOMS", ""),
        help="Comma-separated room ids to attach (default: ROOMBRAIN_ROOMS).",
    )
    p_run.add_argument(
        "--env-file",
        default=".env",
        help="Env file for credentials/connection id (default: %(default)s).",
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
    from roombrain.agent.protocol import RegistrationConflict, read_env_values

    env_path = getattr(args, "env_file", None) or ".env"
    stored = read_env_values(env_path)
    stored_id = (stored.get("ROOMBRAIN_AGENT_ID") or "").strip()
    stored_key = (stored.get("ROOMBRAIN_API_KEY") or "").strip()
    if stored_id and stored_key:
        print("reuse: agent %s already registered, skipping POST" % stored_id)
        return 0
    server = getattr(args, "server", None) or os.environ.get(
        "SWITCH_SERVER_URL", "http://127.0.0.1:8000"
    )
    token = getattr(args, "token", None) or os.environ.get(
        "AGENT_REGISTRATION_TOKEN", ""
    )
    name = getattr(args, "name", None) or "roombrain"
    try:
        from roombrain.agent.protocol import register_agent

        agent_id, _, _ = register_agent(server, token, name, env_path)
    except RegistrationConflict as exc:
        print("reuse: %s" % exc)
        return 0
    except Exception as exc:
        print("register: failed: %s" % exc, file=sys.stderr)
        return 1
    print("registered: agent %s" % agent_id)
    return 0


def cmd_seed_demo(args):
    print("seed-demo: reserved for a later lap (no demo data yet).")
    return 0


def cmd_run(args):
    if getattr(args, "echo", False):
        return run_echo(args.health_port)
    import asyncio

    from roombrain.agent.events import EXIT_TAKEOVER
    from roombrain.agent.protocol import (
        TakenOver,
        load_or_create_connection_id,
        read_env_values,
        run_forever,
    )

    env_path = getattr(args, "env_file", None) or ".env"
    merged = dict(read_env_values(env_path))
    merged.update(os.environ)
    agent_id = (merged.get("ROOMBRAIN_AGENT_ID") or "").strip()
    api_key = (merged.get("ROOMBRAIN_API_KEY") or "").strip()
    if not agent_id or not api_key:
        print(
            "run: missing ROOMBRAIN_AGENT_ID/ROOMBRAIN_API_KEY "
            "(register first)",
            file=sys.stderr,
        )
        return 2
    server = getattr(args, "server", None) or merged.get(
        "SWITCH_SERVER_URL", "http://127.0.0.1:8000"
    )
    rooms = getattr(args, "rooms", None) or merged.get("ROOMBRAIN_ROOMS") or ""
    connection_id = load_or_create_connection_id(env_path)
    try:
        asyncio.run(
            run_forever(
                server,
                agent_id,
                api_key,
                rooms,
                connection_id=connection_id,
                env_path=env_path,
            )
        )
    except TakenOver as exc:
        print("run: evicted: %s" % exc, file=sys.stderr)
        return EXIT_TAKEOVER
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
    print(
        "roombrain: serving /health on 127.0.0.1:%d" % health_port,
        flush=True,
        file=sys.stderr,
    )
    try:
        while True:
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError):
                break  # stdin unreadable: keep serving health.
            if not line:
                break  # EOF: keep serving health until terminated.
            if line.strip():
                try:
                    print(format_echo_line(line), flush=True)
                except BrokenPipeError:
                    pass
        thread.join()
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
