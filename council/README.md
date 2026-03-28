# FairLens Council -- Autonomous AI Advisory System

The Council is a system of specialized AI personas that analyze and advise on every dimension of the FairLens API business. Each persona is a markdown file containing a detailed system prompt. When fed to Claude Code, the persona takes over and produces structured, actionable intelligence specific to FairLens.

## Personas

| Persona | Name | File | Domain |
|---------|------|------|--------|
| Chief Architect | Atlas | `architect.md` | System design, scalability, infrastructure |
| Product Strategist | Meridian | `product_strategist.md` | Market analysis, feature prioritization |
| Revenue Engineer | Forge | `revenue_engineer.md` | Pricing, conversion, monetization |
| Growth Hacker | Vector | `growth_hacker.md` | Marketing, SEO, developer relations |
| IP Strategist | Patent | `ip_counsel.md` | Intellectual property, patents, trade secrets |
| QA Guardian | Sentinel | `qa_guardian.md` | Testing, security, reliability |
| Council Orchestrator | Nexus | `orchestrator.md` | Coordination, unified planning |

## When to Invoke Each Persona

- **Atlas** -- Before any architecture change, when planning new features, when performance degrades, or during scaling discussions.
- **Meridian** -- During quarterly planning, when deciding what to build next, when evaluating competitor moves, or when exploring new markets.
- **Forge** -- When revenue is flat, before changing pricing, when conversion drops, or when planning a new tier.
- **Vector** -- When launching a feature, when traffic stalls, when entering a new market, or monthly for content planning.
- **Patent** -- After building novel features, before publishing technical details, or quarterly for IP portfolio review.
- **Sentinel** -- Before any release, after security incidents, when adding new endpoints, or monthly for audit cycles.
- **Nexus** -- Weekly or biweekly for full council sessions that synthesize all perspectives into a unified action plan.

## How to Use

### Option 1: Copy-Paste into Claude Code

1. Open a persona file (e.g., `council/architect.md`)
2. Copy the entire system prompt section
3. Paste it into a new Claude Code conversation
4. Claude will adopt the persona and analyze your codebase

### Option 2: Run the Shell Script

```bash
# Run a single persona
./council/run_council.sh --persona architect

# Run the full council session (all personas in sequence)
./council/run_council.sh

# Run with a specific focus topic
./council/run_council.sh --persona forge --topic "Q2 pricing changes"
```

### Option 3: Use as a Custom Slash Command

Place persona files in your `.claude/commands/` directory and invoke them as slash commands within Claude Code.

## Output

All persona outputs are saved to `council/reports/` with timestamps:

```
council/reports/
  2026-03-27_atlas_review.md
  2026-03-27_meridian_roadmap.md
  2026-03-27_full_council_session.md
```

## The Autonomous Workflow

The recommended cadence:

1. **Weekly**: Run Nexus (orchestrator) for a full council session. This invokes each persona in sequence and produces a unified action plan.
2. **Before each sprint**: Run Meridian for feature prioritization, then Atlas for technical feasibility review.
3. **Monthly**: Run Forge for revenue analysis, Vector for growth planning, Sentinel for security audit, Patent for IP review.
4. **Ad hoc**: Run any persona when you need focused analysis on their domain.

### Passive Mode (Scheduled Runs)

The orchestrator supports a passive mode described in `orchestrator.md` that outlines how to set up cron-based scheduled council sessions. This lets the council run on autopilot, depositing reports that you review asynchronously.
