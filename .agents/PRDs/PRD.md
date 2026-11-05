# PRD — RoomBrain (Flip the Switch Hackathon 2026)

> Handoff brief for a coding agent. Build target: WeMakeDevs × DevTools Academy × Switch
> "Flip the Switch" hackathon, Nov 4–7 2026 (submissions close **Nov 7, 11:59 PM IST = 7:29 PM WAT**).
> Entry page: https://www.wemakedevs.org/hackathons/switch · Switch repo: https://github.com/sandbox-quantum/switch
> **Updated 2026-11-05:** incorporates the verified Switch protocol (3-tier contract), the
> locked stack, two locked demo decisions, and the compressed Nov 5–7 timeline from the
> design doc at `docs/superpowers/specs/2026-11-05-roombrain-design.md`.

---

## 1. Executive Summary

RoomBrain is a Switch-native agent that turns a team chat into the team's long-term memory.
It joins Mattermost rooms as a teammate, quietly captures decisions and facts as they happen
in conversation, answers recall questions days later with links to the threads where things
were decided, posts a morning brief of what changed, and runs a one-word-approval draft loop
for outbound actions (email, Linear issues).

The hackathon ask is: *connect an AI agent to team chat through Switch so agent + people
complete a real task together.* Every entrant will demo "agent does a task in chat." Almost
none will demo "the chat becomes the team's memory." RoomBrain's differentiation is structural:
a memory vault with hybrid retrieval inside the conversational surface where decisions actually
get made — and it leans on Switch's core primitives (rooms, agents-as-members, `!invite-agent`,
room claiming, ops) rather than treating Switch as plumbing.

**MVP goal:** one self-contained repo that a judge can clone, run against a local Switch server
with bundled Mattermost, invite with `!invite-agent`, and reproduce the 3-minute demo script —
decide something in a thread → RoomBrain remembers → ask later → correct answer with thread
link → draft an announcement → approve with one word → sent.

## 2. Mission

**Mission:** make institutional memory ambient — captured where work happens, retrievable in
the same place, actionable with a single human approval.

**Core principles:**

1. **Switch is the product surface, not a pipe** — rooms, claiming, ops, and room templates are used visibly; Switch must break if you remove it (judging criterion #1).
2. **Human approval for every outbound write** — capture and recall are read-only; sending an email, creating a Linear issue, or posting externally always waits for a one-word yes.
3. **Judge-clonable** — reproducible from `git clone` + README in ≤15 minutes, including the Switch server (Docker Compose profile with bundled Mattermost).
4. **Untrusted chat stays untrusted** — message text is data; it never becomes instructions (delimited, injection-guarded LLM prompts).
5. **Boring tech that works by Nov 7** — Python, SQLite, WebSocket; no novel frameworks in the critical path.

## 3. Target Users

**Primary persona — Techa (demo user):** solo consultant / small AI-automation team lead in
Slack-replacement territory; comfortable with Docker and CLIs; wants their team chat to stop
leaking decisions. Technical comfort: high.

**Secondary persona — the hackathon judge:** wants a clean clone-and-run, a readable README,
and a demo that shows agent + human completing a real task *through Switch*. Technical comfort:
high; time: low.

**Needs/pain points addressed:** decisions buried in scrollback; no single answerable record of
"what did we decide"; repetitive context re-explaining to new members; outbound actions (emails,
tickets) requiring context-switching and copy-paste.

## 4. MVP Scope

### In Scope

**Core functionality**
- [ ] Register RoomBrain on a Switch server (`POST /agents`, persist returned `api_key` to `.env`, never re-register on reboot; 409 → reuse stored key, never `overwrite:true`)
- [ ] WebSocket client: connect `GET /agents/{agent_id}/connection/ws` with `rooms=<id>` on the open URL (declare rooms on the open URL, not after — late subscription loses buffered events), `connection_id` UUID persisted across restarts, read `connection_state` (rooms, cursor, generation — never assumed, server's answer), answer pings **before processing events** with cursor-bearing pongs (`{"type":"pong","cursor":<int>}`)
- [ ] Reconnect fencing: same `connection_id`, `start_from` = highest sequence received, `expected_generation` = last `generation`; cursors only move forward (server ignores a lower one); a `taken_over` eviction is final — do not reconnect
- [ ] Room claiming: primary path is the `rooms=` query param on the open URL; `connect_to_room` op is secondary; act only on `message` events where `payload.addressed == true`
- [ ] Outbound replies go via `POST /agents/{agent_id}/ops/post_message` with `X-Switch-Connection-Id` (WS is inbound-only; there is no documented outbound WS frame)
- [ ] Commands (addressed mentions): `!remember <fact>`, `!recall <query>`, `!decisions [topic]`, `!draft email|linear <topic>`, `!approve` / `!reject`, `!brief`
- [ ] Passive decision capture: latest room messages → LLM extraction → memory entries tagged with room, actor, thread id, timestamp. Batch = **1 message + 2s debounce** (no ≥5-batch rule — a single live decision must be capturable for the demo)
- [ ] Hybrid retrieval: vector (FastEmbed all-MiniLM-L6-v2, 384-dim, sqlite-vec) + FTS5 keyword, 0.7/0.3 blend — port of the proven `memory_search.py` pattern, **not mem0** (mem0 hides room/actor/thread/timestamp provenance; see §8)
- [ ] Approval loop: draft staged in-room → `!approve` executes via Gmail or Linear API → reply with confirmation → draft archived to `sent/` corpus. **Judge path:** if the approving judge has no Gmail token / Linear key, post the rendered draft + "approval recorded; send skipped" and still archive — the gate stays visible, the clone never dead-ends
- [ ] Daily brief: compose from yesterday's captures + room activity, post via standalone `POST /agents/{agent_id}/message` (no live connection required). **This push-path delivery is the demo's Switch-visible beat** — the brief for the 3-minute video is sent with no live socket, so the grader sees Switch doing work a plumbing layer cannot
- [ ] Demo data seeder: `python -m roombrain seed-demo` populates a believable week of decisions for judges
- [ ] README with Switch setup + demo video (≤3 min, script in `/docs`)

**Technical**
- [ ] Python 3.11+, `httpx` (HTTP ops), `websockets` (live socket), `fastembed`, `sqlite-vec`, FTS5
- [ ] Reconnect fencing (above) + idempotent registration; `taken_over` is terminal
- [ ] Prompt-injection guard on all inbound message text before any LLM call
- [ ] `docker-compose.demo.yml` ready (self-host Switch server + `--profile collab` Mattermost) for judges without a Console setup
- [ ] `roombrain/__main__.py` + minimal `Makefile` so `python -m roombrain` and `make setup` (venv + register) work as the README promises

**Integration**
- [ ] Gmail (draft approval → send) via Google OAuth — reuse existing token pattern. **Judge fallback:** no token → approval posts rendered draft + "approval recorded; send skipped", still archives (gate visible, clone intact)
- [ ] Linear (draft issue approval → create) via GraphQL API key. Same judge fallback as Gmail
- [ ] (Stretch) GitHub: PR review-request digest in the brief

**Deployment**
- [ ] Runs on Windows dev box via **Docker self-host** (primary path) and self-hosted Linux server; Windows Console early access is a documented fallback, not the plan

### Out of Scope (defer)

- [ ] CopilotKit Channels SDK port (post-hackathon "Channels-ready" adapter — do not mention competitor in demo)
- [ ] Multi-workspace / multi-tenancy, granular RBAC
- [ ] Voice input (Wispr side track is a stretch goal, not core)
- [ ] Custom native UI beyond Mattermost buttons (no web dashboard)
- [ ] Deep room-linking/Manager fan-out orchestration beyond one demo room pair
- [ ] Slack/Teams connectors (Mattermost only for the entry)
- [ ] **Framework in the critical path** — no LangChain/LangGraph, no FastAPI, no mem0 (see §8). The loop is one fixed shape; a framework adds API surface without removing code.

## 5. User Stories

1. As a **team lead**, I want RoomBrain to notice "let's ship the pricing page Thursday" in a busy thread, so that the decision exists as a queryable record without me writing docs.
   *Example:* `!decisions pricing` → "Thu Nov 6 — pricing page ships Thursday (decided in #launch, thread link)."
2. As a **team member**, I want to ask `@roombrain !recall why are we dropping the OSS tier?` and get the answer plus the thread where it happened, so that I stop re-reading scrollback.
3. As a **team lead**, I want `!draft email <topic>` to produce a send-ready email draft inline, so that I can approve it with `!approve` without leaving chat.
4. As a **cautious teammate**, I want every outbound action blocked until someone with authority replies `!approve`, so that the agent can never send anything unprompted.
5. As a **team member**, I want the morning brief to list yesterday's captured decisions and open action items, so that the day starts from shared state.
6. As a **new hire**, I want `!decisions` on my first day to show the last week of decisions with links, so that onboarding doesn't require a.lifetime oral history.
7. As a **judge**, I want `seed-demo` to populate a realistic room, so that I can test recall quality without staging my own conversations.
8. As the **developer (Techa)**, I want `--dry-run` on capture and a local echo mode, so that I can iterate without burning LLM credits or messaging real rooms.

Technical stories: registration is idempotent (409 → reuse stored key; `overwrite` never used at runtime); socket survives server restarts (reconnect fencing on `generation` + `connection_id`; `taken_over` is terminal — do not reconnect); all LLM calls degrade gracefully to keyword-only recall if the provider is unreachable. **Who may `!approve`:** the room creator if known (from `list_rooms`), else the first regular human participant seen; never an agent sender; persisted in SQLite.

## 6. Core Architecture & Patterns

```
roombrain/
  agent/
    protocol.py        # Switch Rooms client: register → ws connect → claim → dispatch
    ops.py             # op discovery + invocation (X-Switch-Connection-Id header)
    events.py          # event frames: connection_state, ping/pong, message(addressed)
  memory/
    vault.py           # SQLite + sqlite-vec + FTS5 schema, chunk, upsert
    retrieve.py        # hybrid 0.7 vector / 0.3 keyword, thread-link enrichment
  capture/
    extract.py         # decision extractor (LLM, injection-guarded, JSON-out)
    guard.py           # untrusted-text wrapper + instruction-shaped-line filter
  actions/
    gmail_action.py    # draft → approve → send (Gmail API)
    linear_action.py   # draft issue → approve → create (GraphQL)
  brief/
    compose.py         # yesterday's captures + room activity → brief markdown
  roombrain/
    cli.py             # register | run | seed-demo | brief | dry-run modes
  .env.example
  docker-compose.demo.yml
  docs/demo-script.md
  README.md
```

**Patterns:**
- **Event → reason → act loop** (same shape as the proven `zcode_hook.py` → `memory_flush.py` pipeline).
- **Transport-agnostic core:** capture/recall/approval logic never imports the protocol client; a thin `agent/` adapter binds them. (This is what keeps the future Channels SDK port thin.)
- **Two delivery paths:** inbound events over the WebSocket; **outbound replies via `POST /agents/{agent_id}/ops/post_message`** with `X-Switch-Connection-Id` (WS is inbound-only — no documented outbound WS frame; the earlier "live replies over the claimed-room WebSocket" phrasing was wrong), and push-style messages (briefs) via standalone `POST /agents/{agent_id}/message`.
- **Idempotent bootstrap:** `register` writes `ROOMBRAIN_AGENT_ID` / `ROOMBRAIN_API_KEY` to `.env` once; 409 ⇒ reuse; `overwrite:true` is never passed at runtime.

## 7. Tools/Features (agent capabilities)

| Command | Purpose | Mechanics |
|---|---|---|
| `!remember <fact>` | Explicit capture | Direct vault write, confirmation reply |
| `!recall <query>` | Retrieval | Hybrid search → answer + bullet sources (room, date, thread link) |
| `!decisions [topic]` | Digest | Last 7 days' decision-class entries |
| `!draft email <topic>` | Draft | LLM composes from vault context → staged card with ✅ approve / ✖ reject messaging |
| `!draft linear <title>` | Draft | Issue body from vault context → staged |
| `!approve` / `!reject` | Gate | Executes staged action (Gmail send / Linear create), archives draft |
| `!brief` | On demand | Runs the daily brief now |
| Passive capture | Ambient | Every batch of new room messages → extractor → vault (silent unless something saved) |

Passive capture rate-limits itself (batch = 1 message + 2s per-room debounce) and only
stores entries meeting a confidence threshold; extraction output is JSON with a fixed schema.

## 8. Technology Stack

- **Python 3.11+** + `asyncio` — agent runs anywhere Switch runs; judge-clonable.
- `httpx` (ops/HTTP), `websockets` (agent socket), `fastembed` + `sqlite-vec` + SQLite FTS5 (memory), `pydantic` v2 (event/`connection_state`/extraction models), `python-dotenv`, `argparse` (stdlib CLI).
- **LLM:** `openai` SDK pointed at OpenRouter (`base_url=https://openrouter.ai/api/v1`) behind **one `llm()` function** — extraction on a cheap model, synthesis only on `!recall` / `!draft`. Provider is swappable so the README can say "any OpenAI-compatible key." Degrades to keyword-only recall if unreachable.
- **Gmail API** (`google-api-python-client`) + **Linear GraphQL** (raw `httpx`, `LINEAR_API_KEY`) — existing OAuth token + `LINEAR_API_KEY` patterns.
- **Switch:** Docker self-host `ghcr.io/sandbox-quantum/standalone-compose` with `--profile collab --profile gateway` (primary path) + bundled Mattermost; Console early access is a documented fallback, not the plan.
- **Deliberately not used:** FastAPI / any web framework (agent is a client, not a server — Switch serves and handles the push path), LangChain/LangGraph/dspy (loop is event → extract-or-retrieve → respond/approve; one fixed-schema call, no tool-use graph), **mem0** (hides room/actor/thread provenance; OSS build pulls in LangChain/FAISS-class deps), pydantic-ai (considered; unnecessary), Qdrant/Chroma/Redis (second service breaks the 15-minute clone), CopilotKit (post-hackathon adapter only).

## 9. Security & Configuration

- **Env:** `.env` only — `ROOMBRAIN_AGENT_ID`, `ROOMBRAIN_API_KEY` (persisted from registration; never committed), `AGENT_REGISTRATION_TOKEN` (used once during setup, then removed), `OPENROUTER_API_KEY` (or provider key), `GMAIL_OAUTH_TOKEN` path, `LINEAR_API_KEY`. `.env.example` ships, `.env` gitignored.
- **Auth model:** agent `connection_model: always_on`; addressing widened to `owner_and_owner_agents` (never `anyone`). Note: `owner_and_owner_agents` is **not a registration field** — enforce addressing in code (`payload.addressed == true` + `!` prefix on `message.body`); do not wait for a server-side field.
- **Untrusted input:** room text is wrapped in explicit untrusted delimiters in every prompt; extraction LLM is instructed it may only emit the fixed JSON schema; instruction-shaped lines are stripped by `guard.py` before prompting (port of `posting_guard.py` heuristics).
- **Approval gate:** no code path executes Gmail/Linear writes without an in-room `!approve` from the room's owner (room creator if known from `list_rooms`, else first regular human participant seen; never an agent sender; persisted in SQLite); drafts expire after 24h. **Judge fallback:** if the approving judge's Gmail token / Linear key is missing, `actions/` posts the rendered draft + "approval recorded; send skipped" and still archives — gate remains visible, clone never dead-ends. Real-send path remains for key-holding judges.
- **In-scope:** the above. **Out-of-scope:** full RBAC, server hardening beyond README guidance, secrets rotation UX.

## 10. Switch Protocol Contract (tiered by confidence — 2026-11-05)

Fetched from `docs.switchagents.ai/switch-rooms/internals/agent-protocol.md`, `agent-events.md`, `agent-connection.md`. Field names are **verbatim** from the docs. Where this section and earlier PRD prose disagree, this section wins.

### Tier A — Confirmed in docs (safe to code against)

- Register: `POST /agents` with `Authorization: Bearer <registration key>` (one-shot setup key, **separate** from the agent API key — the agent key cannot register). Body: `name` (regex `^[a-z0-9][a-z0-9._-]*$`), `description`, `connector_type` (free-form label, Switch does not check it against a list), `integration_profile` with `connection_model` ∈ `{always_on, session_addressable, auto_session, session_passive}` → use `always_on`, `message_exchange` (bool, required) → `true`, `pre_invocation_mediation` / `post_invocation_mediation` / `event_reporting` ("Send `[]` unless you need them"), optional `command_capabilities`. Optional body fields: `display_name`, `icon_url`, `tools`, `models`, `metadata`, `overwrite`. Response `{"id","api_key"}` — **API key returned once.** 409 on name reuse without `overwrite`; `overwrite:true` mints a **new** key (never use at runtime).
- Socket open: `GET /agents/{agent_id}/connection/ws?connection_id=<uuid>&rooms=<id>` with `Authorization: Bearer <agent API key>`. `connection_id` is "Required. A UUID the client chooses and reuses on every reconnect." `rooms` is "Comma-separated room ids to claim at open, with takeover." **"Declare rooms on the open URL, not after"** — late subscription loses buffered events. `GET /health` is public; a 401 means right host, wrong path.
- First frame `connection_state` (always the first frame on a connection). Fields, verbatim: `connection_id`, `agent_id`, `generation`, `scope`, `filter`, `spawn_capable`, `rooms`, `cursor`, `protocol`, `heartbeat_interval_seconds`, `server`, `client`. "Read it rather than assuming. The rooms list and the cursor are the server's answer, not an echo of the request."
- Liveness: "The server sends a `ping` frame every 2 seconds. Answer each one immediately with a pong that includes your cursor" — `{"type":"pong","cursor":<int>}`. **"Answer pings before you process events."** Cursors only move forward; the server ignores a lower one.
- Reconnect fencing: reopen with the **same `connection_id`**, `start_from` = highest sequence received, `expected_generation` = generation from your last `connection_state`. "The `sequence` on your connection is not a `seq`." **"Reopening a live connection id is a takeover: the second open wins."** The incumbent gets an `evicted` frame with code `taken_over` and its socket closes — **"`taken_over` is final, so don't reconnect after it."**
- Ops: discovery `GET /agents/{agent_id}/ops` → `{"operations": {"<name>": {"description": "...", "input_schema": {...}}, ...}}`; invoke `POST /agents/{agent_id}/ops/{operation}` with `X-Switch-Connection-Id: <connection id>`, body = the arguments object itself (not wrapped), response `{"result": ...}`. Notable ops: `list_rooms`, `create_room`, `connect_to_room`, `post_message`, `send_targeted_message`, `read_context`. `connect_to_room` (want the room's context with the claim) vs `subscribe` (cooperative refusal is right).
- Outbound replies: `POST /agents/{agent_id}/ops/post_message` with `X-Switch-Connection-Id` — **the WebSocket is inbound-only**; there is no documented outbound WS frame. (The earlier "live replies over the claimed-room WebSocket" phrasing was wrong.)
- Push path (no live connection): `POST /agents/{agent_id}/message` with `{room_id, content}` — daily brief.
- Event frames: `message` = `addressed` (bool), `sender`, `sender_name`, `message_id`, `body`, `timestamp` (ms), `thread_id` (nullable), `attachments` (list; pointers — `filename`, `mimetype`, `size`, `mxc`, `msgtype` — never bytes). Act only on `payload.addressed == true`. `sender`/`member` are participant ids `@<localpart>:<server>`. `command` = `command`, `args`, `user_id`, `user_name`, `thread_id` — `command.args` holds role names for `reset`/`compact`, **not** `!` commands — log-only. `room_join` = `member`, `member_name`, `timestamp`, `listening`. Control frames: `connection_state`, `gap`, `evicted`, `subscription_changed`.
- `!` commands are parsed from addressed `message.body` text, not from `command` frames.
- No client library: "There's no client library, so a client you build implements this protocol itself."
- Mattermost: bundled when Console provisions the server (self-host: `collab` profile). Bring the agent into a channel with `!invite-agent @roombrain` **as the first text in a message**. Buttons need `Callback Base Url` (default port 8081) reachable from Mattermost.
- Self-host env: `AGENT_REGISTRATION_TOKEN`, `SECRET_KEYS` (`<id>:<secret>`, ≥32 chars), `GATEWAY_ADMIN_EMAIL`/`GATEWAY_ADMIN_PASSWORD`, `ID_SERVER_NAME`, `GATEWAY_PUBLIC_URL`; API port 8000, gateway 3000.
- Full docs: https://docs.switchagents.ai/switch-rooms/getting-started/index.md

### Tier B — Stated in prose, wire-unconfirmed (Phase 0 spike MUST confirm before coding)

1. **Reconnect query-parameter names** (`start_from`, `expected_generation`) — stated in prose, not in a quoted code block. Confirm against the live server or `agent-connection.md` at kickoff.
2. **Placements route path** — a post-open room-claim route exists with `connection_id`, `placements`, `generation` in and `{placements, rooms, released}` out, but the docs page names the fields, not the URL. Optional if the `?rooms=` URL-claim is used; do not block MVP on it.
3. **Room identity on `message` frames** — the `message` payload table in `agent-events.md` does not list a room-id field. The builder must confirm how room identity is carried (frame envelope vs payload) on the wire in Phase 0.

### Tier C — Unknown (Phase 0 spike resolves)

- Gap-frame semantics and backfill (proposed: log `gap`, backfill via `read_context` or reconnect with the last cursor; ignore `subscribe` for MVP).

**Rule:** "Verified" applies to Tier A only. Anything in Tier B/C is spike-gated — write it into `agent/events.py` as pydantic models from wire capture, never from prose alone.

## 11. Success Criteria

**MVP = success if:**
- [ ] `git clone` + README steps → working RoomBrain on a fresh Switch server with Mattermost in ≤15 min
- [ ] Demo script reproduces end-to-end without internet beyond LLM API + Switch/Mattermost downloads
- [ ] Recall answers a question asked 2+ "days" after the decision, citing the thread (seeded data acceptable)
- [ ] No outbound action executes without `!approve`
- [ ] Demo video ≤3 min (5 distinct live messages for the passive beat + a 30-second Switch-visible beat: raw register/connect frame or Console session → `!invite-agent` → brief arriving via the push path with no live socket)
- [ ] **Two locked demo decisions:** (1) the demo task is Switch-visible — at least one beat proves Switch doing work a plumbing layer cannot (push-path brief with no live connection, or Console/rooms/claim evidence); (2) judges with no Gmail token / Linear key get the dry-run approval path (rendered draft + "approval recorded; send skipped" + archive) — the gate stays visible, the clone never dead-ends
- [ ] All 4 judging criteria explicitly addressed in README ("Why this needs Switch" section)

## 12. Implementation Phases

**Phase 0 — De-risk (Nov 5 — today; gates everything)**
- Goal: prove the protocol loop on the actual machine, and resolve every Tier B / Tier C item in §10 against the wire before coding anything else.
- Deliverables: [ ] Docker self-host running (`ghcr.io/sandbox-quantum/standalone-compose` + `--profile collab --profile gateway`); [ ] hello-world agent registered + replies to one addressed message in a Mattermost room via `!invite-agent`; [ ] registration reuse verified; [ ] **Tier B/C spike capture:** reconnect query-param names, room-id carrier on `message` frames, placements route (optional) — captured from the wire and encoded as pydantic models in `agent/events.py`; [ ] `taken_over` fencing confirmed.
- Validation: round-trip message in ≤60s of process start; Tier B/C unknowns resolved on the wire. **If Docker self-host fails, do not spend time on Windows Console early access — fall back to Linux VPS / disposable VPS / macOS machine.**

**Phase 1 — Skeleton (Nov 5–6)**
- Goal: always-on agent skeleton + repo scaffold.
- Deliverables: [ ] `protocol.py` (register/connect/claim/heartbeat/reconnect fencing), [ ] `!remember`/`!recall` with keyword-only store, [ ] CLI (`register|run`, dry-run) + `roombrain/__main__.py` + minimal `Makefile`, [ ] `.env.example`.
- Validation: `!remember X` then `!recall X` live in a room.

**Phase 2 — Memory + capture (Nov 6)**
- Goal: the differentiator works.
- Deliverables: [ ] vector+FTS5 hybrid retrieval (0.7/0.3), [ ] passive extraction loop w/ `guard.py` (batch = 1 + 2s debounce), [ ] `!decisions`, [ ] `seed-demo` seeder (**believable week**, `--live` creates real rooms/messages via `post_message` for real thread links; `--local` fallback uses synthetic IDs flagged as synthetic in the README).
- Validation: seeded week (believable 7 days, thread links live) → `!recall` answers with correct thread citation target ≥90% on 30 seeded queries.

**Phase 3 — Actions + brief + submission (Nov 6)**
- Goal: complete demo + ship.
- Deliverables: [ ] Gmail + Linear approval loop (with judge dry-run fallback), [ ] daily brief, [ ] `docker-compose.demo.yml`, [ ] README incl. "Why this needs Switch", [ ] 3-min demo video (5 distinct live messages for the passive beat + 30-second Switch-visible beat: raw register/connect frame or Console session → `!invite-agent` → push-path brief with no live socket), [ ] submit before Nov 7 7:29 PM WAT (submit Nov 7 morning WAT — feature freeze Nov 6 night WAT).
- Validation: full demo script from cold start; submission receipt.

**Buffer — Nov 7:** fixes, blog write-up (AirPods side track), #HowISwitch post, `hackathon`-labeled issue PRs if time remains.

## 13. Future Considerations

- CopilotKit Channels SDK adapter (native Slack/Teams cards) — the transport-agnostic core makes this thin; deliberately excluded from the entry.
- Manager-pattern room linking: #decisions room auto-creates per-project rooms and fans context (Switch room links/groups ops).
- Voice capture via Wispr Flow; meeting-notes ingestion; Slack/Teams connectors post-GA; subscription service for small teams.

## 14. Risks & Mitigations

1. **Windows Console is early access and could block Phase 0** → Docker self-host is the primary path (Linux-only officially, but Docker Desktop runs it on Windows) + Mattermost web client; fallback order: Linux VPS / disposable VPS → macOS machine. Do not spend Phase 0 time on Console.
2. **Protocol details drift (repo is "current development line, not released product")** → Phase 0 is a raw-protocol spike against the live server; pin to the Tier A contract in §10 and resolve Tier B/C on the wire in Phase 0; re-check `agent-events.md` / `agent-connection.md` at kickoff.
3. **Registration key returned only once** → persist immediately, idempotent CLI, never run register twice without `--force` (which uses `overwrite: true` knowingly).
4. **Takeover eviction is terminal** → single `connection_id` per process, persisted across restarts; never auto-reconnect a `taken_over` socket.
5. **Timezone deadline miss** → hard rule: feature freeze Nov 6 night WAT; submission Nov 7 morning WAT, not evening.
6. **Passive capture noise / LLM cost** → batch = 1 + 2s per-room debounce, confidence threshold; extraction on cheap model, synthesis only on `!recall` / `!draft`.

## 15. Appendix

- Entry & rules: https://www.wemakedevs.org/hackathons/switch
- Switch docs root: https://docs.switchagents.ai/switch-rooms/index.md (llms index: https://docs.switchagents.ai/llms.txt)
- Protocol details: `/switch-rooms/internals/agent-protocol.md`, `agent-connection.md`, `agent-events.md`, `collaboration-bridge.md`
- Getting started / self-host: `/switch-rooms/getting-started/index.md`, `/switch-rooms/deploy/self-host.md`
- Messaging/Mattermost: `/switch-rooms/deploy/messaging-apps/mattermost.md`
- Design doc (2026-11-05, builder-checked; §6/§8/§13 carry the verified protocol contract, stack rationale, and builder-owned decisions): `docs/superpowers/specs/2026-11-05-roombrain-design.md`
- Internal prior art (vault, port don't import — repo must stand alone): [brainstorm](SecondBrain/Memory/projects/switch-hackathon-2026-brainstorm.md) · [Channels SDK research](SecondBrain/Memory/projects/switch-hackathon-2026-channels-sdk-research.md) · RAG stack: `SecondBrain/.opencode/scripts/memory_search.py`
- Judge clone path: README → Docker self-host setup → `make setup` (venv + register) → `seed-demo` (believable week, `--live`) → `run` → `!invite-agent @roombrain` in Mattermost → demo script (`docs/demo-script.md`).
