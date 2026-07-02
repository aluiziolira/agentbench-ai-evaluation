# AgentBench demo recording
#
# Regenerate with:  vhs docs/demo.tape   (run from the repo root)
#
# Prerequisites:
#   - infrastructure up and seeded:  just init && just services-bg
#   - vhs, ttyd, ffmpeg installed
#
# The recording uses whatever adapters the runtime was started with; set
# AGENTBENCH_MOCK_LLM=1 in .env to run the demo with zero API spend.
#
# Note: fixed Sleeps are used instead of Wait+Screen — polling the screen
# while a command is streaming output can deadlock ttyd's flow control.

Output docs/demo.gif

Require just
Require uv

Set Shell "bash"
Set FontSize 15
Set Width 1300
Set Height 840
Set Padding 16
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set BorderRadius 8
Set Framerate 30
Set TypingSpeed 30ms

# --- hidden setup: load .env so the CLI reaches MongoDB directly -------------
Hide
Type "set -a; source .env; set +a; clear"
Enter
Sleep 1s
Show

# --- beat 1: quality gate ------------------------------------------------------
Type "# AgentBench — event-driven AI agent evaluation. First: the test suite."
Sleep 800ms
Enter
Sleep 300ms

Type "just test-unit"
Sleep 400ms
Enter
Sleep 7s

Type "clear"
Sleep 300ms
Enter

# --- beat 2: full benchmark, 2 agents x 8 cases --------------------------------
Type "# Benchmark 2 agents against 8 seeded PR-review cases (Redis Streams pipeline)"
Sleep 800ms
Enter
Sleep 300ms

Type "just demo"
Sleep 400ms
Enter
Sleep 18s
Sleep 3s

Type "clear"
Sleep 300ms
Enter

# --- hidden: grab the latest benchmark + run ids --------------------------------
Hide
Type `BENCH=$(uv run python -c "import os; from pymongo import MongoClient; print(MongoClient(os.environ['MONGODB_URI'])[os.environ.get('MONGODB_DB', 'agentbench')]['benchmark_reports'].find_one(sort=[('created_at', -1)])['benchmark_id'])" | tail -1); RUN=$(ls -t data/raw_io | head -1); clear`
Enter
Sleep 4s
Show

# --- beat 3: the headline leaderboard -------------------------------------------
Type "# Reports are persisted in MongoDB — pull the leaderboard back anytime"
Sleep 800ms
Enter
Sleep 300ms

Type "uv run python -m cli.main report $BENCH --demo --no-per-case"
Sleep 400ms
Enter
Sleep 4s
Sleep 6s

Type "clear"
Sleep 300ms
Enter

# --- beat 4: re-score stored output under a new rubric --------------------------
Type "# Every agent response is stored as raw I/O — re-score it with a new rubric,"
Sleep 600ms
Enter
Type "# without re-invoking the agent. Zero additional API cost."
Sleep 600ms
Enter
Sleep 300ms

Type `uv run python -m cli.main rescore --run-id $RUN --step s2_review_summary --strategy llm_judge --rubric "Prioritize production risk above all else"`
Sleep 600ms
Enter
Sleep 5s
Sleep 7s
