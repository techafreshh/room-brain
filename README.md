# RoomBrain — team memory that lives where decisions get made

RoomBrain is a Switch agent that turns team chat into team memory. It
passively captures decisions, answers `!recall` with dated bullets carrying
thread links, stages Gmail/Linear drafts behind an owner-only approval gate,
and pushes a morning brief. Stdlib-only runtime (`argparse` + `http.server`
+ `sqlite3` + `urllib`); no web framework, no ORM, no new pip dependencies.

> Freeze note: feature freeze Nov 6 night WAT, submit Nov 7 morning WAT.
> This README is the judge-cloneable path: clean clone to live demo in
> under 15 minutes.

## Quickstart (clone to demo in <= 15 min)

Prerequisites: Docker, Python 3.11+, `make`.

1. Start the Switch self-host + collab Mattermost stack:
   ```sh
   docker compose -f docker-compose.demo.yml up
   ```
   (shortcut: `make demo-up`). Switch API lands on
   `http://127.0.0.1:8000`, Mattermost on `http://127.0.0.1:8065`.
   If Docker is unavailable, the Console-hosted Switch is the fallback
   (point `SWITCH_SERVER_URL` at it) — the rest of the steps are identical.
2. Set up the venv:
   ```sh
   make setup
   ```
3. Copy the env template and fill one secret:
   ```sh
   cp .env.example .env
   ```
   Set `AGENT_REGISTRATION_TOKEN` in `.env` to the same value as in the
   compose file. Defaults already work: `SWITCH_SERVER_URL` defaults to
   `http://127.0.0.1:8000`, and `ROOMBRAIN_NO_EMBED=1` stays the default
   reply path so `run` never blocks on a FastEmbed download.
4. Register the agent (idempotent; safe to re-run):
   ```sh
   python -m roombrain register --server http://127.0.0.1:8000 --token "$AGENT_REGISTRATION_TOKEN"
   ```
   First run `POST /agents` persists `ROOMBRAIN_AGENT_ID`/`ROOMBRAIN_API_KEY`
   to `.env` and prints `registered: agent <id>`. Re-runs print
   `reuse: agent <id> already registered, skipping POST` — a 409 on name
   reuse never overwrites the stored key.
5. Seed the believable demo week (offline default, no network):
   ```sh
   python -m roombrain seed-demo --local
   ```
   Prints `seeded 24 memories (mode=local)` with synthetic `synth-*`
   thread ids. Optional live variant posts every entry for real thread
   links: `python -m roombrain seed-demo --live` (requires registration
   first; exits 2 with a "register first" hint otherwise).
6. Run the always-on loop:
   ```sh
   python -m roombrain run
   ```
   (shortcut: `make run-demo`). Connects over the Switch WebSocket with a
   stable connection id, answers addressed `!`-commands via
   `POST /agents/{id}/ops/post_message`, one POST per command.
7. Invite the agent in Mattermost: open a channel and send as the **first
   text of a message**:
   ```
   !invite-agent @roombrain
   ```
   Then run the demo script below. `!remember` then `!recall` round-trips
   within 60s of `run` starting on a seeded vault.

Verify the loop without Switch (health + echo smoke):
```sh
python -m roombrain run --echo --health-port 18081
curl http://127.0.0.1:18081/health   # {"status":"ok"}
```

## Invite

RoomBrain joins rooms the Switch way — rooms claim agents, not the other
way around:

- In any Mattermost channel backed by the collab profile, post
  `!invite-agent @roombrain` as the first text in a message. Switch adds
  the agent as a room member and starts delivering addressed messages.
- The agent records the first human speaker as the room owner
  (`ensure_owner`); the approval gate later restricts `!approve` to that
  owner (or the draft requester).
- Re-invites are harmless: registration and room claiming are both
  idempotent, and reconnects reuse the same connection id with
  `start_from`/`expected_generation` fencing (a `taken_over` eviction
  exits 3 instead of retrying).

## Demo (5 live messages + 30s Switch-visible beat)

Full shot-by-shot script with timestamps: `docs/demo-script.md` (3 min
runtime). The table below is the message spine:

| # | You send | Agent replies (via `POST /agents/{id}/ops/post_message`) |
|---|----------|----------------------------------------------------------|
| 1 | `!remember launch checklist frozen, pricing review Thursday` | `remembered "launch checklist frozen, ..." (vault now holds N)` |
| 2 | `!recall pricing` | `recall: 2 hit(s) for "pricing":` + dated bullets with `room#thread` links |
| 3 | `!decisions` | `decisions (last 7 days):` + dated bullets |
| 4 | `!draft email launch plan` | `draft d1 staged (email): launch plan -- reply !approve d1 or !reject d1` |
| 5 | `!approve d1` | `approval recorded; send skipped (draft d1 archived to sent/d1.md)` |

The 30-second Switch-visible beat: raw register/connect frame (or Console
session) -> `!invite-agent @roombrain` in Mattermost -> `python -m
roombrain brief` (or `!brief` in chat) arriving via the push path
`POST /agents/{agent_id}/message` with no live socket. Keyless
Gmail/Linear stays dry-run by design: the gate posts the rendered draft,
records `approval recorded; send skipped`, and archives the markdown to
`sent/`.

## Why this needs Switch

A plain chatbot can answer questions; only Switch makes the chat itself
the system of record. RoomBrain leans on five Switch primitives that no
plumbing of webhooks or polling replaces:

- **Rooms as the trust boundary.** Decisions are captured per room with
  per-room owners; recall and the approval gate both scope to the room
  the message arrived in.
- **Claiming (`!invite-agent`).** Membership is granted inside the chat
  surface by the humans who own the room — no out-of-band provisioning,
  no service account to babysit.
- **Ops (`POST /agents/{id}/ops/post_message`).** The WebSocket is
  inbound-only; every reply goes out as exactly one ops POST, which is
  what makes the `!remember`/`!recall` round-trip testable end to end.
- **Addressing.** Only addressed messages dispatch (`message_body`
  returns `None` otherwise), so passive channel chatter is captured but
  never triggers a reply storm.
- **Push path (`POST /agents/{id}/message`).** The morning brief reaches
  the room with no live socket, which is the Switch-visible beat of the
  demo: Console session -> invite -> brief lands.

Against the four judging criteria: (1) *Agent quality* — keyword-first
recall with dated thread links, never a stalled embedding download;
(2) *Switch leverage* — rooms, claiming, ops, addressing, and the push
path are all load-bearing, not decorative; (3) *Reproducibility* — this
README plus `docker-compose.demo.yml` plus `seed-demo --local` is the
whole judge path, no secrets committed; (4) *Completeness* — capture,
recall, gate with dry-run fallback, and brief all ship behind one CLI.

## Fallbacks (judge-friendly by design)

- **Keyless Gmail/Linear is dry-run, not an error.** With no
  `GMAIL_OAUTH_TOKEN` / `LINEAR_API_KEY`, `!approve` still records the
  approval, prints `approval recorded; send skipped`, and archives the
  rendered draft to `sent/<draft>.md`. Set the tokens to get real sends
  (the reply then starts with `sent email d1 ...`).
- **Keyword-only recall.** `ROOMBRAIN_NO_EMBED=1` is the default, so
  recall always answers from the local vault even with no model
  downloaded. Unset it to opt into hybrid embedding retrieval.
- **`seed-demo --local` is the default judge path.** Synthetic `synth-*`
  thread ids, zero network. `--live` re-seeds through real `post_message`
  calls for clickable thread links.
- **Console early-access fallback.** If the self-host bundle will not
  start, point `SWITCH_SERVER_URL` at a Console-provisioned server and
  continue from step 3 — no other step changes.
- **Expired / unauthorized drafts fail safe.** Approving a draft older
  than 24h reports `expired`; approving from an agent/bot sender or a
  non-owner reports `not authorized: only the room owner can approve`.
  Nothing is ever sent twice: one command, one POST.

## Reference

- `docker-compose.demo.yml` — Switch (`8000`) + Mattermost (`8065`) demo
  stack; `collab` + `gateway` image profiles via `command:`.
- `docs/demo-script.md` — 3 min video script (timestamps, beats, fallback).
- `Makefile` — `setup` / `test` / `smoke` plus `demo-up`, `register`,
  `seed-local`, `run-demo`, `brief` shortcuts used above.
- `python -m roombrain --help` — `register` | `seed-demo --local|--live` |
  `run [--echo]` | `brief [--room]`.
- `.env.example` — every key the demo needs; `.env` itself stays
  gitignored, no secrets committed.

## Troubleshooting

- `run: missing ROOMBRAIN_AGENT_ID/... (register first)` — run step 4
  first; check `.env` was written.
- `reuse: agent ... already registered, skipping POST` — not an error;
  registration is idempotent by design.
- `seed-demo --live` exits 2 — register first so `.env` holds the id/key.
- Port `8000` busy — stop the other Switch, or override with
  `SWITCH_SERVER_URL=http://127.0.0.1:8001` and matching compose ports.
- `brief: missing room` — pass `--room #launch` or set `ROOMBRAIN_ROOMS`.
- Replies feel slow — confirm `ROOMBRAIN_NO_EMBED=1` (default); embedding
  downloads never block the reply path unless you opt out of it.
