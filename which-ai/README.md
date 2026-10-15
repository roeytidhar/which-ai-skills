# Which-AI: The Intent-Based Orchestrator

Welcome to Which-AI! This is a simple but powerful skill designed to help AI agents and developers match tasks to the best Large Language Model for the job. 

Choosing the right model can be tricky. You want the highest intelligence for complex tasks, but you also want to manage your budget and respect the environment the agent is running in (like local versus cloud). Which-AI solves this by automatically routing requests based on real world data.

## What it does

Which-AI acts as a dynamic router. It takes three simple inputs:
1. **Budget:** How much are you willing to spend per million input tokens?
2. **Deployment:** Are you running this in the `cloud` or on a `local` machine?
3. **Modality:** Do you need `text`, `vision`, or `coding` capabilities?

Using these inputs, the skill ranks models by their current LMArena (Arena) leaderboard rating (Hugging Face `lmarena-ai/leaderboard-dataset`) and live OpenRouter prices. For local use you pass the machine's RAM (`--ram`) and it only suggests open models that fit at 4-bit.

## How to use this skill

This skill is designed to be easily plugged into any agentic platform that supports markdown based skills.

### Supported Platforms
Which-AI works seamlessly with:
* Claude Code
* OpenCode
* Claude CoWork
* Any custom agent framework that supports standard skill schemas

### Adding Which-AI to your project

1. Clone or download this repository.
2. Copy the `which-ai` folder into your project's skills or tools directory.
3. Make sure your agent has permission to execute bash scripts and run Python.

### Using Which-AI in Claude CoWork

Which-AI is natively structured to be a Claude CoWork plugin! Here is exactly how to install it:
1. Open your Claude CoWork environment.
2. Click the `+` icon next to the "Personal" tab in the "Browse plugins" menu.
3. Select **Add plugin - personal** (if prompted), then click the `+` icon again.
4. Select **Add marketplace from GitHub**.
5. Enter `roeytidhar/which-ai-skills` in the URL field and click **Sync**.
6. Hover over the **Which AI** card and click **Install**.
7. Now just ask Claude: "Can you use the which-ai skill to find a coding model under $3?" and watch it work!

## Contributing

We would absolutely love your help to make Which-AI even better. Whether it is adding new data sources, improving the scoring heuristic, or adding new platforms, your contributions are welcome. Feel free to open an issue or submit a pull request!
