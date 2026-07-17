# Working Journal

A running log of what I'm building and learning on my own time.

## Learning agentic loops

- [ ] Read up on plan-act-check loops and where they get stuck.
- [ ] Understand why bounded iteration + budget caps matter for unattended runs.
- [x] Sketch a tiny agent in `projects/ai-experiments/agent.py`.

I keep coming back to the same idea: I want an assistant that notices what I'm
already working on and *proposes* the next useful goal, instead of waiting for me
to spell everything out. That "proactivity layer" feels like the interesting part.

## Personal project ideas

- Turn the tiny agent into something that can scaffold a new project from a short
  description: write a learning plan, then a project scaffold, then stop.
- Add an offline evaluation harness so I can iterate without any API keys.

## Job search notes

- [ ] Refresh my portfolio around the agent-loop project -- it's the clearest
      demonstration of systems thinking I have right now.
- [ ] Draft talking points on how retries, backoff, and checkpoints make an
      unattended loop trustworthy.
- Interviews keep asking how I'd keep a long-running job resilient to throttling;
  the retry-with-backoff work here is a good concrete story.

## Reminders

- Keep everything runnable offline. No network in tests. No secrets in the repo.
