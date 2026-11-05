# RoomBrain

Walking skeleton: a minimal end-to-end loop from a clean clone. Stdlib only
(`argparse` + `http.server`), no Switch, no LLM, no third-party dependencies.

## Quickstart

```sh
make setup
python -m roombrain --help
python -m roombrain run --echo --health-port 18081
curl http://127.0.0.1:18081/health
```

The health endpoint answers `{"status":"ok"}`. The `run --echo` loop replies
to each stdin line with `echo: <line>`.

## Layout

- `roombrain/__main__.py` — `python -m` entrypoint.
- `roombrain/cli.py` — CLI (`register` | `run` | `seed-demo`), health server, echo loop.
- `Makefile` — `setup` / `test` / `smoke` targets.
- `.env.example` — placeholder env keys for later laps.
- `tests/test_skeleton.py` — stdlib unittest suite.

## Vision

See `PRD-roombrain-switch-hackathon.md` for the full product vision.
