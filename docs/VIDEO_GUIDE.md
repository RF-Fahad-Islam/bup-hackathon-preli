# 3-minute solution video: script and shot list

**Hard limit: 3:00.** The official guide says the video must be *no longer than 3 minutes*. It must also explain four things: the problem, the architecture overview, the solution approach (the LLM → guardrails → optimizer flow), and how the system is run and tested. The video earns no base points. It is used only to break ties, so it pays to be clear and calm rather than flashy.

The script below is about **420 spoken words**, which fits in about 2:50 at a normal pace (around 150 words a minute). Every scene lists what to **show** and what to **say**. Speak in your own words if you like, but keep to the times.

---

## Before you record

- [ ] Start the server in a terminal and make it large: font size 18 or more, dark theme.
  - macOS / Linux: `uvicorn app.main:app --port 8080`
  - Windows: `.venv\Scripts\python -m uvicorn app.main:app --port 8080`
- [ ] Open a **second terminal** in the project folder with the virtual environment active.
- [ ] Open the README on GitHub, scrolled to the **"How it works, in simple words"** diagram.
- [ ] Open `samples/official/requests/SAMPLE-09.json` in your editor. This is the "80% reduction" sample.
- [ ] Open three code files in tabs: `app/llm.py` (the `SYSTEM_PROMPT`), `app/directives.py` and `app/optimizer.py`.
- [ ] **Hide all secrets.** Close `.env`, don't `echo` any keys, and check the terminal history on screen.
- [ ] Warm the server once by sending any sample, so the live demo answers instantly.
- [ ] Use OBS, Loom or the Windows Game Bar (`Win + Alt + R`) at 1080p. Record the microphone, not system sounds.

---

## Timeline

| Time | Scene | Screen |
|---|---|---|
| 0:00 – 0:25 | 1. The problem | README top / a slide |
| 0:25 – 0:55 | 2. Architecture | README mermaid diagram |
| 0:55 – 1:35 | 3. LLM + guardrails | `SAMPLE-09.json`, `llm.py`, `directives.py` |
| 1:35 – 2:05 | 4. Optimizer + auditor | `optimizer.py`, `replay.py` |
| 2:05 – 2:45 | 5. Live demo and tests | Terminal |
| 2:45 – 3:00 | 6. Wrap-up | README table |

---

### Scene 1: The problem (0:00 – 0:25)

**Show:** the top of the README, or a slide with a campus, solar panels, a battery and the grid.

**Say:**
> "Hi, we're team ___. GridWise plans a campus's electricity for the next 24 hours: when to buy from the grid, use solar, or charge and use the battery, so the bill is as low as possible.
> The twist: operators leave plain-English notes, like 'panels are washed from noon to 2 PM'. Our service must understand them and obey them exactly."

---

### Scene 2: Architecture (0:25 – 0:55)

**Show:** the four-box diagram in the README. Point at each box as you name it.

**Say:**
> "We split the work into four parts.
> An LLM **reads** the notes.
> Plain code **checks** the LLM's answer. We never trust it blindly.
> A math solver **plans** the cheapest schedule.
> And an **auditor** replays the plan hour by hour, like the judge, before we send it.
> The AI handles language; everything exact is done by ordinary code."

---

### Scene 3: LLM + guardrails (0:55 – 1:35)

**Show:** the note in `SAMPLE-09.json` ("80% reduction"), then the `SYSTEM_PROMPT` in `app/llm.py`, then `raw_to_directive` in `app/directives.py`.

**Say:**
> "Our key idea: LLMs understand language well but slip on arithmetic. They might read '11 AM to 2 PM' as four hours, or '80% reduction' as 0.8.
> So the LLM only reports what the note literally says: '11 to 14, 80 percent, reduction', in a strict JSON schema with one of six allowed types.
> Our code does the math. The end hour is excluded, so the hours are 11, 12 and 13, and 80% less means factor 0.2. It also rejects anything invalid, like unknown types or hours outside 0 to 23.
> A fast Groq model reads first and a small pattern checker double-checks it. If they disagree, a stronger model decides. If a provider fails, OpenRouter is the backup."

---

### Scene 4: Optimizer + auditor (1:35 – 2:05)

**Show:** `solve()` in `app/optimizer.py`, then scroll `app/replay.py`.

**Say:**
> "The optimizer writes the day as a linear program: grid, solar, charge, discharge and battery level for every hour. It adds energy balance, battery limits, every operator rule, and one more: the battery must end the day where it started.
> The HiGHS solver returns the proven cheapest plan. Our tests confirm it against a brute-force search.
> Then the auditor re-checks every hour and recomputes the totals. A plan that breaks a rule is never sent."

---

### Scene 5: Live demo and tests (2:05 – 2:45)

**Show:** type these in the second terminal, one after another.

```bash
curl http://127.0.0.1:8080/health
curl -X POST http://127.0.0.1:8080/optimize-energy -H "Content-Type: application/json" -d @samples/official/requests/SAMPLE-09.json
python scripts/run_samples.py http://127.0.0.1:8080 samples/official
pytest -q
```

On Windows PowerShell, type `curl.exe` instead of `curl`.

After the second command, scroll up to `"hours": [11, 12, 13]` and `"factor": 0.2` and highlight them.

**Say:**
> "Health is OK. We send sample 9: '80% reduction between 11 AM and 2 PM' became factor 0.2 for hours 11 to 13, and tomorrow's club notice became no-op. Below is the 24-hour plan and cost.
> All ten public samples pass with the exact reference cost, each in under a second.
> 89 automated tests pass, including 400 random scenarios, and 42 re-worded notes were all read correctly by the real LLM."

---

### Scene 6: Wrap-up (2:45 – 3:00)

**Show:** the table at the top of the README.

**Say:**
> "So: the LLM reads, code checks and calculates, the solver optimizes, and the auditor verifies. It runs with one command or one Docker image. Thank you!"

---

## Easy words for tricky terms (if a judge asks)

| Term | Simple meaning |
|---|---|
| **Operator note** | A short message from the campus energy staff, written in normal English |
| **Directive** | The machine-readable meaning of a note: one of six allowed types |
| **`no_op`** | "This note doesn't change today's plan", for example a cafeteria menu or something happening tomorrow |
| **Guardrail** | Code that checks the LLM's answer and refuses anything outside the rules |
| **Tripwire** | A small pattern-based reader that only decides whether to ask a stronger model for a second opinion |
| **Escalation** | Sending a note to the stronger model when the first answer looks doubtful |
| **Linear program (LP)** | A math problem, "minimize the cost subject to these equations and limits", that a solver answers exactly |
| **HiGHS** | The open-source solver that finds the cheapest plan |
| **Replay / auditor** | Re-running the finished plan hour by hour to prove it breaks no rule |
| **Battery neutrality** | The battery must end the day at the same level it started |
| **End-exclusive window** | "11 AM to 2 PM" means hours 11, 12 and 13, not 14 |
| **Factor** | How much solar is **left**: an 80% reduction means factor 0.2 |

## Final checks before uploading

- [ ] The length is **3:00 or less**. Trim pauses if needed.
- [ ] No API key, `.env` file or token is visible in any frame.
- [ ] Text on screen is readable at 720p.
- [ ] The link is set to "anyone with the link can view" (YouTube *unlisted* or Google Drive). Test it in a private browser window.
- [ ] The link is pasted into the submission form and the README.
