# RoomBrain — Design

**Date:** 2026-11-05
**Source PRD:** `PRD-roombrain-switch-hackathon.md` (Flip the Switch Hackathon 2026)
**Entry:** WeMakeDevs × DevTools Academy × Switch — submissions close **Nov 7, 11:59 PM IST = 7:29 PM WAT**
**Status:** Draft — pending reviewer + human approval
**Repository:** `/home/techafresh/projects/room-brain` (greenfield; only the PRD exists today)

---

## 1. Intent and the why

RoomBrain is a Switch-native agent that turns a Mattermost team chat into the team's long-term memory. It joins rooms as a teammate, quietly captures decisions and facts as they happen in conversation, answers recall questions days later with links to the threading where things were decided, posts a morning brief of what changed, and runs a one-word-approval draft loop for outbound actions (email, Linear issues).

The hackathon ask is: *connect an AI agent to team chat through Switch so agent + people complete a real task together.* Every entrant will demo "agent does a task in chat." Almost none will demo "the chat becomes the team's memory." RoomBrain's differentiation is structural — a memory vault with hybrid retrieval inside the conversational surface where decisions actually get made — and it leans on Switch's core primitives (rooms, agents-as-members, `!invite-agent`, room claiming, ops) rather than treating Switch as plumbing.

**Why this shape, why now.**

1. The entry is judged on agent + human completing a real task *through Switch*. A task that only works because Switch exists will score. A task that could run over any chat API will read as plumbing.
2. The bottleneck during the hackathon is clone reproducibility, not sophistication. A judge should be able to run `git clone` + README and see the 3-minute demo within 15 minutes on a fresh Switch server with bundled Mattermost.
3. "Decide something in a thread → RoomBrain remembers → ask later → correct answer with thread link → draft an announcement → approve with one word → sent" is a single, memorizable script. It is the only script we optimize around.
4. The transport-agnostic core keeps the future CopilotKit Channels SDK port thin, but that is post-hackathon. We do not build for it now.

---

## 2. Goals, non-goals, anti-goals

### Goals

- **G1 — Judge-clonable MVP.** One self-contained repo a judge can clone, run against a local Switch server with bundled Mattermost, invite with `!invite-agent`, and reproduce the 3-minute demo script end-to-end in ≤15 minutes.
- **G2 — Memory as the differentiator.** Passive capture of decisions from conversation, queryable via `!decisions` / `!recall` with room + actor + thread link for every answer.
- **G3 — Switch load-bearing.** If you remove Switch, the product breaks. Rooms, claiming, ops, and addressing are used visibly in the demo, not as a wrapper around a chat API.
- **G4 — Human approval for every outbound write.** Capture and recall are read-only. Sending an email, creating a Linear issue, or posting externally always waits for a one-word `!approve` from the room owner (or owner agent).
- **G5 — Untrusted chat stays untrusted.** Message text is data; it never becomes instructions. Inbound text is delimited and injection-guarded before any LLM call.

### Non-goals

- CopilotKit Channels SDK port (post-hackathon thin adapter; do not mention competitors in the demo).
- Multi-workspace / multi-tenancy, granular RBAC.
- Voice input (Wispr side track is stretch, not core).
- Custom native UI beyond Mattermost buttons (no web dashboard).
- Deep room-linking / Manager fan-out orchestration beyond one demo room pair.
- Slack/Teams connectors (Mattermost only for this entry).
- Anything that requires a novel framework in the critical path (see §7).

### Anti-goals

- **A1 — No outbound action without `!approve`.** Even a perfectly reasonable email must not send without explicit in-room approval. This is a safety property, not a UX preference — it is tested.
- **A2 — No "Switch is plumbing."** If a checkpoint can be satisfied without calling a Switch op, it is not a valid demo step. The README's "Why this needs Switch" section is the contract.
- **A3 — No secrets in git.** `.env` is gitignored; `ROOMBRAIN_API_KEY` is never re-registered at runtime, never committed, and never printed to logs.
- **A4 — No novel frameworks in the critical path.** Boring Python that works by Nov 7 > elegant abstraction.

---

## 3. Constraints

Derived from the PRD, the user's answers, and today being **Nov 5** (hackathon started Nov 4; PRD phases were written assuming Nov 2–3 Phase 0).

| # | Constraint | Source |
|---|---|---|
| C1 | **Switch runs as Docker self-host locally** (`ghcr.io/sandbox-quantum/standalone-compose` with `--profile collab --profile gateway`), bundled Mattermost. Same path judges follow. | User answer |
| C2 | **LLM via OpenRouter**, behind a single provider function (`openai` SDK with `base_url=https://openrouter.ai/api/v1`). Extraction on cheap model; synthesis only on `!recall` / `!draft`. Degrades to keyword-only recall if provider unreachable. | User answer |
| C3 | **Python 3.11+**; stack = `httpx` (ops/HTTP), `websockets` (agent socket), `fastembed` + `sqlite-vec` + SQLite FTS5 (memory), `pydantic` v2, `python-dotenv`, `asyncio`. | PRD §8 |
| C4 | **No framework in the critical path.** No LangChain/LangGraph, no FastAPI (agent is a client, not a server), no CopilotKit. CLI is `argparse` stdlib. | §7 verdict |
| C5 | **Connection model `always_on`**; addressing widened to `owner_and_owner_agents`, never `anyone`. | PRD §9 |
| C6 | **Idempotent registration.** `register` writes `ROOMBRAIN_AGENT_ID` / `ROOMBRAIN_API_KEY` to `.env` once; 409 → reuse stored key; `overwrite:true` is never used at runtime (would mint a new key and fence the old connection). | PRD §10 + docs |
| C7 | **Hard freeze Nov 6 night WAT; submit Nov 7 morning WAT** (not evening — deadline is 7:29 PM WAT). Buffer Nov 7 for fixes only. | PRD §14 |
| C8 | **`seed-demo` ships a believable week of decisions** (7 days, multiple rooms/topics, thread links) so judges see passive-capture quality immediately. | User answer |
| C9 | **No client library exists for Switch Rooms.** Protocol must be hand-implemented. Verified against docs (see §6 verified contract). | docs.switchagents.ai |
| C10 | **Chat is untrusted.** Every LLM prompt wraps room text in explicit untrusted delimiters; extraction LLM may only emit a fixed JSON schema; instruction-shaped lines are stripped by `guard.py` before prompting. | PRD §9 |
| C11 | **Drafts expire after 24h.** No code path executes Gmail/Linear writes without an in-room `!approve` from the room owner; drafts archived to `sent/` corpus after execution. | PRD §9 |
| C12 | **Windows dev box compatibility** via Docker Desktop (Switch Console early access is the PRD's Phase 0 risk; Docker self-host is the chosen path). | PRD §14 |

---

## 4. Approaches

Three approaches were considered in the brainstorm. Two were eliminated; one is recommended.

### Approach A — PRD-faithful single-process agent (RECOMMENDED)

One Python process:
- `agent/protocol.py` — register → WS connect → claim → dispatch (hand-implemented Switch protocol, see §6 contract).
- Transport-agnostic core: `capture/`, `memory/`, `actions/`, `brief/` never import `agent/`; `agent/` remains a thin adapter so the future Channels SDK port stays thin.
- Live replies over the claimed-room WebSocket; push-style messages (daily brief, out-of-band draft confirmations) via standalone `POST /agents/{id}/message` — no live connection required.
- Memory is SQLite with FTS5 + sqlite-vec; extraction is a fixed-schema JSON LLM call behind `guard.py` delimiters.

**Tradeoffs:**
- ✅ Judge-clone is `pip install` + `seed-demo` + `run` — ≤15 min, no extra services.
- ✅ Switch is genuinely load-bearing: remove `agent/` and nothing works. Satisfies judging criterion #1 directly.
- ✅ Matches the proven `zcode_hook.py` → `memory_flush.py` event→reason→act shape from prior art.
- ✅ No extra infrastructure to debug on Nov 7.
- ⚠️ Single-process means capture, retrieval, and approval share fate — a crash takes all three down. Mitigation: supervisor reconnect on `generation` change (see §6); process is tiny, restart is cheap.
- ⚠️ SQLite caps at one host — irrelevant for a hackathon demo.

### Approach B — Split memory service + agent process (REJECTED)

A separate retrieval microservice (HTTP) the agent calls for `!recall` / `!decisions`.

- ❌ Doubles judge setup (second service, second port, second env).
- ❌ Doubles failure modes on the clone path for zero demo benefit — the memo is in-process SQLite, latency is sub-millisecond.
- ❌ Splits the audit trail (capture and retrieval logs live in different places), hurting the "where was this decided" provenance story.

Rejected on C1 (judge-clonable ≤15 min) and C4 (boring tech).

### Approach C — LLM-orchestration framework (REJECTED)

Wrap capture/recall/drafting in LangGraph (or LangChain/dspy).

- ❌ The loop is a single fixed shape (event → extract or retrieve → act/approve). There is no multi-agent tool-use graph to orchestrate.
- ❌ Adds framework API surface to learn, pin, and debug in 48 hours. The PRD explicitly bans novel frameworks in the critical path (C4).
- ❌ PRD's extraction output is a fixed JSON schema — a framework buys nothing over a single function call with `pydantic` validation.

Rejected on C4. The only framework ever seriously considered was **pydantic-ai** (lightweight, Starlette-style, OpenRouter built-in); it was dropped because the agent socket + approval gate are the novelty, not agent logic — one function behind a provider interface is simpler and easier to mock in tests.

**Why not mem0** (raised by user, considered and rejected — documented for judges):

Mem0 is a memory *layer* (add/search/update over a vector store + LLM). RoomBrain is not generic agent memory — it is **chat-decision archaeology**: every entry must carry room, actor, thread id, timestamp, and a link back to the exact thread for `!recall` answers. Mem0's API hides that metadata model and assumes its own store (and even its OSS build pulls in LangChain/FAISS-class dependencies). We would end up fighting it to keep the provenance the judges need, while still paying for a second vector store on top of SQLite. The PRD's 0.7/0.3 hybrid is trivial in plain SQLite (`sqlite-vec` + FTS5). Mem0 would make sense if RoomBrain were a multi-user personal assistant remembering user preferences across apps; for a Switch-room memory vault, native SQLite wins on judge-clone time and auditability.

**Base-agent note.** The Switch repo (`github.com/sandbox-quantum/switch`) ships only YAML agent templates (`examples/agent-templates/*.template.yaml`: jq-expert, support-desk, switch-expert, triage-pair) and `room-templates/`. **There is no Python agent starter to copy** — `agent/protocol.py` is genuinely greenfield and Phase 0's spike is not redundant. The YAML templates are worth a peek before writing the final `POST /agents` body so our agent description rhymes with how Switch expects agents to describe themselves.

**Recommendation: Approach A.** It is the only approach that makes Switch load-bearing, stays judge-clonable, and fits the Nov 7 freeze. All downstream implementation follows Approach A.

---

## 5. Architecture

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
  cli.py               # register | run | seed-demo | brief | dry-run modes
  docs/
    demo-script.md     # 3-min script (judge-facing)
  docker-compose.demo.yml
  .env.example
  README.md
```

**Patterns (unchanged from PRD, restated for the builder):**

- **Event → reason → act loop.** One socket reader; handlers are pure-ish functions (`memory/vault.py`, `memory/retrieve.py`, `capture/extract.py`) that never import `agent/`.
- **Transport-agnostic core.** `capture/`, `memory/`, `actions/`, `brief/` do not import `agent/`. `agent/` is the only module that knows about Switch. This is what keeps the future Channels SDK port thin — and it is also what makes the code testable without a live Switch server.
- **Two delivery paths.** Live replies over the claimed-room WebSocket; push-style messages (daily brief) via standalone `POST /agents/{id}/message` (no live connection required).
- **Idempotent bootstrap.** `register` writes `ROOMBRAIN_AGENT_ID` / `ROOMBRAIN_API_KEY` to `.env` once; 409 ⇒ reuse stored key. `overwrite:true` is never passed at runtime.
- **Reconnection fencing.** On reconnect, reopen with same `connection_id`, `start_from` = highest sequence received, `expected_generation` = last `generation`. The connection-id sequence is **not** `seq`; cursors only move forward. A `taken_over` eviction is final — do not reconnect.
- **Approval gate.** No code path executes Gmail/Linear writes without an in-room `!approve` from the room owner (or owner agent). Drafts expire after 24h and are archived to `sent/` after execution.
- **Graceful degradation.** All LLM calls degrade to keyword-only recall if the provider is unreachable. `seed-demo` works without any LLM key.

**Commands (addressed mentions only; act only when `payload.addressed == true`):**

| Command | Purpose | Mechanics |
|---|---|---|
| `!remember <fact>` | Explicit capture | Direct vault write, confirmation reply |
| `!recall <query>` | Retrieval | Hybrid search → answer + bullet sources (room, date, thread link) |
| `!decisions [topic]` | Digest | Last 7 days' decision-class entries |
| `!draft email <topic>` | Draft | LLM composes from vault context → staged card with ✅ approve / ✖ reject messaging |
| `!draft linear <title>` | Draft | Issue body from vault context → staged |
| `!approve` / `!reject` | Gate | Executes staged action (Gmail send / Linear create), archives draft |
| `!brief` | On demand | Runs the daily brief now (also runs via push path on schedule) |
| *(passive)* | Ambient capture | Every batch of new room messages → extractor → vault (silent unless something saved) |

Passive capture rate-limits itself (≥5 new messages per batch, per-room debounce, confidence threshold); extraction output is fixed-schema JSON.

---

## 6. Switch Protocol — Verified Contract (2026-11-05)

Fetched from `docs.switchagents.ai/switch-rooms/internals/agent-protocol.md`, `agent-events.md`, `agent-connection.md` plus the `github.com/sandbox-quantum/switch/examples` directory. Field names below are **verbatim** from the docs. Where the PRD's §10 cheat sheet differs from this contract, **this section wins**.

### 6.1 Registration — `POST /agents`

- Auth: `Authorization: Bearer <registration key>` — a one-shot setup key, **separate** from the agent API key. The agent key cannot register.
- Body (required):
  - `name` — regex `^[a-z0-9][a-z0-9._-]*$`
  - `description`
  - `connector_type` — "A free-form label. Switch doesn't check it against a list"
  - `integration_profile`:
    - `connection_model` — one of `always_on`, `session_addressable`, `auto_session`, `session_passive` → **use `always_on`**
    - `message_exchange` — boolean, required → `true`
    - `pre_invocation_mediation`, `post_invocation_mediation`, `event_reporting` — "Send `[]` unless you need them"
    - Optional: `command_capabilities`
- Body (optional): `display_name`, `icon_url`, `tools`, `models`, `metadata`, `overwrite`
- Response: `{"id", "api_key"}` — **API key returned once.**
- 409 on name reuse without `overwrite`. With `overwrite: true` it succeeds but **issues a new API key** — therefore **never pass `overwrite:true` at runtime** (C6).

### 6.2 WebSocket connection

```
GET /agents/{agent_id}/connection/ws?connection_id=<uuid>&rooms=<id>
Authorization: Bearer <agent API key>
Upgrade: websocket
```

- `connection_id` — "Required. A UUID the client chooses and reuses on every reconnect."
- `rooms` — "Comma-separated room ids to claim at open, with takeover."
- **"Declare rooms on the open URL, not after."** Late subscription loses buffered events. (PRD's "claim via `connect_to_room` op after open" is therefore the *secondary* path; the URL is the primary.)
- `GET /health` is public. A 401 means right host, wrong path.

**First frame — `connection_state`** (always the first frame on a connection). Fields, verbatim: `connection_id`, `agent_id`, `generation`, `scope`, `filter`, `spawn_capable`, `rooms`, `cursor`, `protocol`, `heartbeat_interval_seconds`, `server`, `client`.
- Instruction: "Read it rather than assuming. The rooms list and the cursor are the server's answer, not an echo of the request."
- `generation` — "keep `generation` for your next reconnect" (see fencing below).

### 6.3 Reconnect fencing + takeover

- Reopen with the **same `connection_id`**, `start_from` set to the **highest sequence received**, and `expected_generation` set to the **generation from your last `connection_state`**.
- **"The `sequence` on your connection is not a `seq`."** `start_from` and the `cursor` in a pong use that sequence. "Cursors only move forward. The server ignores a cursor lower than the one it holds."
- **"Reopening a live connection id is a takeover: the second open wins."** The connection it took over gets an `evicted` frame with code `taken_over`, and its socket closes. **"`taken_over` is final, so don't reconnect after it."**
- Builder note: the exact reconnect query-parameter names (`start_from`, `expected_generation`) are stated in prose in the docs; they are **not** in a quoted code block. Before coding the reconnect path, confirm the exact parameter names against a live server in Phase 0 (or `agent-connection.md` at kickoff) — this is the single highest-risk detail in the contract.

### 6.4 Liveness (ping/pong)

- "The server sends a `ping` frame every 2 seconds. Answer each one immediately with a pong that includes your cursor" — format: `{"type": "pong", "cursor": <int>}`.
- **"Answer pings before you process events."** (Pong handling is higher priority than event dispatch. The cursor is the unacked position — it advances as events are processed; the server ignores a cursor lower than the one it holds, so never regress it.)
- `heartbeat_interval_seconds` in `connection_state` is authoritative over the "2 seconds" prose.

### 6.5 Ops

- Discovery: `GET /agents/{agent_id}/ops` → `{"operations": {"<name>": {"description": "...", "input_schema": {...}}, ...}}`
- Invocation: `POST /agents/{agent_id}/ops/{operation}` with header `X-Switch-Connection-Id: <connection id>`; body is the **arguments object itself, not wrapped**; response is `{"result": ...}`.
- Notable ops: `list_rooms`, `create_room`, `connect_to_room`, `post_message`, `send_targeted_message`, `read_context`.
- `connect_to_room` vs `subscribe`: "Use `connect_to_room` when the session wants the room's context with the claim, and `subscribe` when a cooperative refusal is the right outcome."
- Room-claim placement route (post-open) uses `connection_id`, `placements`, `generation`; returns `{placements, rooms, released}` — builder must confirm the exact HTTP path for this route in Phase 0 (the docs page names the fields, not the URL).

### 6.6 Event frames

Domain events:

- **`message`** — `addressed` (bool), `sender`, `sender_name`, `message_id`, `body`, `timestamp` (ms), `thread_id` (nullable), `attachments` (list). Act **only** when `payload.addressed == true`. "`sender` and `member` hold a participant id, in the form `@<localpart>:<server>`." Room id is **not** listed as a field in the `message` payload table — the builder must confirm how room identity is carried (frame envelope vs payload) in Phase 0.
- **`command`** — `command`, `args` (empty by default), `user_id`, `user_name`, `thread_id` (nullable). "`command.args` holds the role name to re-assume for `reset` and `compact`."
- **`room_join`** — `member`, `member_name`, `timestamp`, `listening` (bool).

Control frames: `connection_state`, `gap`, `evicted`, `subscription_changed`.

Attachments (`filename`, `mimetype`, `size`, `mxc`, `msgtype`) are **pointers, never bytes**.

### 6.7 Push path (no live connection)

- `POST /agents/{agent_id}/message` with `{room_id, content}` — no connection needed. Used for the daily brief and any out-of-band delivery.

### 6.8 Mattermost

- Bundled when Console provisions the server; for self-host, bundled via the `collab` profile.
- Bring the agent into a channel with `!invite-agent @roombrain` **as the first text in a message**.
- Buttons need `Callback Base Url` (default port 8081) reachable from Mattermost.

### 6.9 Self-host environment

- `AGENT_REGISTRATION_TOKEN`, `SECRET_KEYS` (`<id>:<secret>`, ≥32 chars), `GATEWAY_ADMIN_EMAIL` / `GATEWAY_ADMIN_PASSWORD`, `ID_SERVER_NAME`, `GATEWAY_PUBLIC_URL`.
- API port 8000, gateway 3000.
- Full docs: `https://docs.switchagents.ai/switch-rooms/getting-started/index.md`

---

## 7. Technology Stack

Chosen, with the rejected alternatives named so judges can see the reasoning.

### Used

| Area | Choice | Why |
|---|---|---|
| Runtime | **Python 3.11+ + `asyncio`** | One process, one event loop: WS connect → `connection_state` → claim → dispatch. No framework needed for that shape. |
| Agent socket | **`websockets`** | Cursor-bearing pongs, reconnect on `generation` change. |
| HTTP / ops | **`httpx`** | Sync-in-async friendly. All `POST /agents`, `GET /ops`, `POST /ops/{op}`, `POST /agents/{id}/message`, Linear GraphQL replaceable by any OpenAI-compatible client. |
| Memory vectors | **`fastembed` (`all-MiniLM-L6-v2`, 384-dim, ONNX) + `sqlite-vec` + SQLite FTS5** | Hybrid 0.7 vector / 0.3 keyword — a port of the proven `memory_search.py` pattern. No torch, no separate vector DB. |
| LLM | **`openai` SDK pointed at OpenRouter** (`base_url=https://openrouter.ai/api/v1`) behind **one `llm()` function** | Extraction on a cheap model, synthesis only on `!recall` / `!draft`. Provider is swappable; judges hear "any OpenAI-compatible key." Degrades to keyword-only. |
| Models | **Pydantic v2** | Event frames, `connection_state`, decision-extraction JSON schema, config. |
| Config | **`python-dotenv`** + `.env.example` | Persist `ROOMBRAIN_AGENT_ID` / `ROOMBRAIN_API_KEY` once, 409 → reuse. |
| CLI | **`argparse` (stdlib)** | `register \| run \| seed-demo \| brief \| dry-run`. No Click/Typer — fewer deps, easier clone. |
| Gmail | **`google-api-python-client`** | Draft approval → send, reusing the existing OAuth token pattern. |
| Linear | **Raw `httpx` GraphQL** (`LINEAR_API_KEY`) | No SDK wrapper to learn; one mutation. |
| Tests | **`pytest` + `pytest-asyncio`** | Core modules (`memory/`, `capture/`, `actions/`) import nothing from `agent/` — testable without a live Switch server. |
| Lint/format | **`ruff`** | Matches Switch repo's `ruff.toml` idiom. |
| Packaging | **`pyproject.toml`** | Single installable unit; `pip install -e .` in README quickstart. |
| Deploy | **`docker-compose.demo.yml`** | Switch self-host + `--profile collab` Mattermost. For judges without a Console setup. |

### Deliberately not used

- **FastAPI / any web framework** — the agent is a *client* of Switch, not a server. The push path (`POST /agents/{id}/message`) is handled by Switch, and Mattermost buttons hit Switch's Callback Base Url. There is nothing to serve.
- **LangChain / LangGraph / dspy** — the processing loop is event → extract-or-retrieve → respond/approve. There is no tool-use graph to orchestrate. A framework would add API surface without removing code (see Approach C).
- **mem0** — see §4 "Why not mem0". Wrong shape for decision archaeology; hides the provenance metadata judges need.
- **pydantic-ai** — the only framework seriously considered. Dropped: socket + approval gate are the novelty, not agent logic. One `llm()` function is simpler and easier to mock.
- **Qdrant / Chroma / Redis** — a second service breaks the 15-minute clone. SQLite in the same process answers the whole demo.
- **CopilotKit Channels SDK** — post-hackathon adapter only. Explicitly excluded from the demo.

---

## 8. Security and configuration

### Environment (`.env` only)

```
ROOMBRAIN_AGENT_ID
ROOMBRAIN_API_KEY            # persisted from registration; never committed
AGENT_REGISTRATION_TOKEN     # used once during setup, then removed
OPENROUTER_API_KEY           # or any OpenAI-compatible provider key
GMAIL_OAUTH_TOKEN_PATH       # path to existing token file
LINEAR_API_KEY
```

`.env.example` ships; `.env` is gitignored. `#3` in PRD §14 Risks is non-negotiable: the registration key is returned **once**. `register` must persist immediately and be idempotent; `register` twice without `--force` is a bug, and `--force` must use `overwrite: true` knowingly.

### Auth model

- `connection_model: always_on`; addressing widened to `owner_and_owner_agents` (never `anyone`).
- Room claiming on the socket open URL (`rooms=<id>`); `connect_to_room` op as the secondary path only.

### Untrusted input

- Every inbound message is wrapped in explicit **untrusted delimiters** in every prompt.
- The extraction LLM may only emit the fixed JSON schema (validated by `pydantic`).
- `guard.py` strips instruction-shaped lines before prompting (port of `posting_guard.py` heuristics from prior art).
- Message text is data, never instructions. This is a testable property: the same message, with and without an injected instruction, must produce the same vault writes.

### Approval gate

- **No code path executes Gmail/Linear writes without an in-room `!approve` from the room owner (or owner agent).**
- Drafts expire after 24h.
- After execution, drafts are archived to the `sent/` corpus for later `!recall`.
- `!reject` discards the staged draft without executing.
- The gate is enforced in `actions/` (which has no `agent/` import); the in-room `!approve` is the only signal that triggers execution.

### Out of scope (explicitly)

Full RBAC, server hardening beyond README guidance, secrets rotation UX.

---

## 9. Demo script

The 3-minute script judges will see. Everything is the happy path; failures are handled in §10.

1. **0:00 — Cold start.** `docker compose -f docker-compose.demo.yml up` (Switch + Mattermost). `make setup` (venv + register). `python -m roombrain seed-demo` → "week of decisions loaded." `python -m roombrain run`.
2. **0:30 — Decide in a thread.** In Mattermost `#launch`: "Let's ship the pricing page Thursday." RoomBrain is silent (passive capture is ambient). Behind the scenes: batched extraction → vault entry tagged `#launch`, actor, thread id.
3. **0:50 — Recall days later.** Same room: `@roombrain !recall why ship Thursday?` → answer + "Thu Nov 6 — pricing page ships Thursday (decided in #launch, thread link)." Full script is multi-step; use the scripted demo for the 3-minute video cut.
4. **1:10 — Digest.** `@roombrain !decisions pricing` → last 7 days' pricing decisions.
5. **1:30 — Draft.** `@roombrain !draft email pricing page launch` → staged email draft inline (LLM composed from vault context).
6. **1:50 — Approve.** Room owner: `!approve` → Gmail sends → RoomBrain replies "Sent. Archived to memory." Draft moves to `sent/` corpus.
7. **2:10 — Brief.** `@roombrain !brief` (or scheduled push via `POST /agents/{id}/message`) → yesterday's captures + open action items.
8. **2:30 — Close.** README's "Why this needs Switch" section on screen: rooms, claiming, ops, addressing, push path — every step above named the Switch primitive it used.

**Demo data (`seed-demo`):** a believable week of decisions — 7 days across multiple rooms/topics with thread links (pricing, OSS tier, launch date are the demo-critical set). Content must be fixed in the repo so the demo is deterministic. Seeder generates embeddings locally; no LLM key required.

---

## 10. Risks and mitigations

Carried forward from PRD §14, plus one new risk discovered during protocol verification.

1. **Phase 0 protocol unknowns (new, from §6.3/§6.5/§6.6).** The docs state reconnect parameter names (`start_from`, `expected_generation`) and the `placements` route fields in prose, not in quoted code blocks; room identity on `message` frames is not listed in the payload table. **Mitigation:** Phase 0 is a raw-protocol spike against the live Docker self-host server *before* any memory/approval code — confirm the three unknowns against the wire, write them into `events.py` as pydantic models, and never code against prose alone.
2. **Protocol drift (repo is "current development line, not released product").** PRD §14 already names this. **Mitigation:** Phase 0 spike against the live server; re-check `agent-events.md` / `agent-connection.md` at kickoff; pin to the §6 contract in this document.
3. **Registration key returned only once.** **Mitigation:** persist immediately in `register`, idempotent CLI, never run `register` twice without `--force` (which uses `overwrite: true` knowingly).
4. **Takeover eviction (new, from §6.3).** Reopening a live `connection_id` evicts the incumbent with `taken_over` (final). **Mitigation:** single `connection_id` per process, persisted across restarts; never auto-reconnect a `taken_over` socket.
5. **Windows Console is early access and could block Phase 0.** **Mitigation:** chosen path is Docker self-host (C1). Fallback order: Docker Desktop on the same Windows box → Linux VPS / disposable VPS → macOS machine.
6. **Timezone deadline miss (Nov 7, 7:29 PM WAT).** **Mitigation:** hard feature freeze Nov 6 night WAT; submission Nov 7 morning WAT, not evening. Buffer Nov 7 for fixes + blog + #HowISwitch post only.
7. **Passive capture noise / LLM cost.** **Mitigation:** batched extraction (≥5 msgs/batch, per-room debounce) + confidence threshold; extraction on cheap model, synthesis only on `!recall` / `!draft`.

---

## 11. Success criteria (MVP = success if)

- [ ] `git clone` + README steps → working RoomBrain on a fresh Switch server with Mattermost in ≤15 min.
- [ ] Demo script (§9) reproduces end-to-end without internet beyond LLM API + Switch/Mattermost downloads.
- [ ] Recall answers a question asked 2+ "days" after the decision, citing the thread (seeded data acceptable).
- [ ] No outbound action executes without `!approve` (tested).
- [ ] Demo video ≤3 min; README shows Switch usage prominently.
- [ ] All 4 judging criteria explicitly addressed in README ("Why this needs Switch" section).

---

## 12. Implementation phases (compressed — today is Nov 5)

The PRD's original phase dates assumed Phase 0 on Nov 2–3. We are already in the hackathon, so phases compress:

| Phase | Dates | Goal | Validation |
|---|---|---|---|
| **0 — De-risk (gates everything)** | Nov 5 | Prove the protocol loop on the actual machine: Docker self-host up, hello-world agent registered, `!invite-agent`, one addressed round-trip; confirm §6.3/§6.5/§6.6 unknowns against the wire. | Round-trip message in ≤60s of process start; `connection_state` + fencing + takeover semantics confirmed on the wire. |
| **1 — Skeleton** | Nov 5–6 | `protocol.py` (register/connect/claim/heartbeat/reconnect), `!remember`/`!recall` keyword-only, CLI + `.env.example`. | `!remember X` → `!recall X` live in a room. |
| **2 — Memory + capture** | Nov 6 | Vector+FTS5 hybrid retrieval, passive extraction loop with `guard.py`, `!decisions`, `seed-demo` (believable week). | Seeded week → `!recall` answers with correct thread citation target ≥90% on 30 seeded queries. |
| **3 — Actions + brief + ship** | Nov 6 | Gmail + Linear approval loop, daily brief, `docker-compose.demo.yml`, README incl. "Why this needs Switch", 3-min demo video, submit before Nov 7 7:29 PM WAT. | Full demo script from cold start; submission receipt. |
| **Buffer** | Nov 7 | Fixes, blog write-up, #HowISwitch post, `hackathon`-labeled issue PRs if time remains. | — |

---

## 13. What's left to the builder

The builder owns these implementation choices; they do not change the architecture:

- **Exact model IDs** for extraction (cheap) vs synthesis (smarter) on OpenRouter, behind the single `llm()` function. Read from env with sane defaults.
- **Chunking** in `memory/vault.py` (messages vs decision entries vs synthesized facts) and upsert semantics (dedupe by thread+content hash).
- **Confidence threshold** and batch size for passive extraction; per-room debounce interval.
- **Staged-draft storage** (SQLite table vs in-memory + archive) and the staged-card message format (Mattermost buttons via Callback Base Url vs plain-text ✅/✖).
- **Linear GraphQL mutation** shape (issue create fields) and Linear project/team defaults.
- **Gmail send path** (OAuth token reuse pattern from prior art — port, don't import).
- **`brief/compose.py` format** — markdown structure for yesterday's captures + open action items.
- **Logging**: structured JSON to stdout; never log `api_key`, `Authorization` headers, or `LINEAR_API_KEY`.
- **Test boundaries**: `memory/`, `capture/`, `actions/`, `brief/` tested with mocked LLM; `agent/` tested against a live Docker self-host in Phase 0 and mocked thereafter.

The builder does **not** own: the command surface (§5), the verified protocol contract (§6), the stack (§7), the approval gate (§8), or the demo script (§9). Any change to those goes back through the human.

---

## 14. Alternatives considered (expanded)

For completeness. All are also in §4; expanded here with the "what would have to be true to revisit this" note the builder may need later.

- **mem0 (memory layer)** — Rejected for MVP. Revisit only if RoomBrain grows into a multi-user personal assistant remembering preferences across apps, and `sqlite-vec` stops being sufficient (e.g., >1M entries across many rooms). The provenance requirement (room/actor/thread/timestamp on every entry) is the permanent mismatch.
- **LangGraph / LangChain** — Rejected. Revisit only if the processing loop grows a real tool-use graph (e.g., multi-step research for `!recall`). Today: one function call, fixed JSON schema.
- **pydantic-ai** — Rejected as unnecessary. Revisit only if the codebase hits multiple LLM tools and the provider-abstraction overhead starts paying for itself.
- **Split memory microservice** — Rejected. Revisit only if the process needs to scale beyond one Docker host — not a hackathon concern.
- **FastAPI server mode** — Rejected. The agent is a client; Switch serves. Revisit only if a web dashboard becomes a requirement (explicitly out of scope).
- **Single-process in-memory state (no SQLite)** — Rejected. The product *is* persistent memory; restarts must not lose the vault.

---

## 15. Appendix — Pointers

- Entry & rules: https://www.wemakedevs.org/hackathons/switch
- Switch repo: https://github.com/sandbox-quantum/switch
- Switch docs root: https://docs.switchagents.ai/switch-rooms/index.md (llms index: https://docs.switchagents.ai/llms.txt)
- Protocol details: `/switch-rooms/internals/agent-protocol.md`, `agent-connection.md`, `agent-events.md`, `collaboration-bridge.md`
- Getting started / self-host: `/switch-rooms/getting-started/index.md`, `/switch-rooms/deploy/self-host.md`
- Messaging/Mattermost: `/switch-rooms/deploy/messaging-apps/mattermost.md`
- Internal prior art (vault, port don't import): `brainstorm` (SecondBrain/Memory/projects/switch-hackathon-2026-brainstorm.md), Channels SDK research (SecondBrain/Memory/projects/switch-hackathon-2026-channels-sdk-research.md), RAG stack: `SecondBrain/.opencode/scripts/memory_search.py`
- Judge clone path: README → Docker self-host setup → `make setup` (venv + register) → `python -m roombrain seed-demo` → `python -m roombrain run` → `!invite-agent @roombrain` in Mattermost → demo script (`docs/demo-script.md`)
