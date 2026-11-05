# RoomBrain demo video script — 3 min

Runtime: 3 min. One take, no cuts: cold clone to live memory to gated send.
Prereqs (off-camera): Docker up via `docker compose -f
docker-compose.demo.yml up`, `make setup`, `.env` copied from
`.env.example`, agent registered, `seed-demo --local` done. What the camera
sees starts at a clean terminal in the repo root.

## 0:00 — Cold start (0:00-0:30)

Show the empty vault and the one-command run:

```sh
python -m roombrain run
```

Say: "Fresh clone, seeded offline, one process. The loop connects with a
stable connection id and answers only addressed messages — one command in,
one POST out."

## 0:30 — Passive capture note (0:30-1:00)

Say: "Teammates just talk. Every channel message is captured to the vault
with room, actor, and thread id — chatter never triggers a reply, only
addressed `!`-commands dispatch. Now five live messages."

Send each of these as its own addressed chat message (each line below is
one message; each gets exactly one reply via
`POST /agents/{id}/ops/post_message`):

```
!remember launch checklist frozen, pricing review Thursday
```

Reply: `remembered "launch checklist frozen, ..." (vault now holds N)`.

```
!recall pricing
```

Reply: `recall: 2 hit(s) for "pricing":` plus dated bullets with
`room#thread` links.

```
!decisions pricing
```

Reply: `decisions (last 7 days):` plus dated bullets.

```
!draft email launch plan
```

Reply: `draft d1 staged (email): launch plan -- reply !approve d1 or
!reject d1`.

```
!approve d1
```

Reply: `approval recorded; send skipped (draft d1 archived to
sent/d1.md)`.

Alternate sixth beat if time allows (swap for `!decisions` on a tight run):

```
!brief
```

Reply: the morning brief markdown for the room (Decisions + Activity
lines), delivered over the ops path.

Say after #5: "That fallback is the gate beat: with no Gmail or Linear
key, the approval is still recorded — approval recorded; send skipped —
and the rendered draft is archived to `sent/` instead of sent. Set the
tokens and the same `!approve` performs a real send."

## 1:50 — 30s Switch-visible beat (1:50-2:20)

This is the Switch-only moment — pause the chat and show the wire:

1. Show the raw register/connect frame (or the Console session view):
   `POST /agents` 200 with the agent id, then the WebSocket
   `connection_state` with generation + cursor.
2. In a fresh Mattermost channel, send as the first text of a message:

```
!invite-agent @roombrain
```

3. With no live socket for the target room, push the brief:

```sh
python -m roombrain brief --room "#launch"
```

Say: "Invite claims the room from inside chat, and the brief arrives via
the push path — POST /agents/{agent_id}/message — with no live socket open
for that room. Rooms, claiming, and push: that is why this needs Switch,
not webhooks."

Evidence the camera holds for 5 seconds: the Mattermost channel showing
the agent as a member after `!invite-agent` (rooms-claim evidence) plus
the brief message landing via push.

## 2:20 — Fallback + close (2:20-3:00)

Show `sent/d1.md` in the terminal and say: "Keyless judges still see the
whole loop — draft, owner-only approve, dry-run archive. Keyword recall
answers with zero model download because `ROOMBRAIN_NO_EMBED=1` is the
default."

Close on the checklist: connect, invite, five commands, one push, one
archived send — 3 min, reproducible from this repo with
`docker compose -f docker-compose.demo.yml up`, `make setup`, register,
`seed-demo --local`, `run`.

## Shot list (for the editor)

- [ ] 0:00 terminal: `python -m roombrain run` connects (connection_state).
- [ ] 0:30 five `!` messages sent, five replies, each one ops POST.
- [ ] 1:50 register frame + `!invite-agent @roombrain` + push brief via
  `POST /agents/{agent_id}/message` with no live socket.
- [ ] 2:20 `approval recorded; send skipped` + `sent/d1.md` on screen.
- [ ] Total runtime 3 min (hard cap; trim the `!brief` alternate first).
