# PC context for the assistant
<!-- Edit freely. This file is loaded into the agent's prompt on every request. Keep it short and factual. -->

## Hardware
- Hostname: 
- CPU: 
- GPU: 
- Monitors:
- Peripherals: 
## Software
- OS:
- AUR helper: 
- Terminal: Bar:  Notifications: 
- Dotfiles repo: 
- Local LLMs: Ollama (gpt-oss:20b for this agent, qwen2.5vl:7b for images and screenshots)

## How to help
- The user wants diagnosis and clear explanations. Gather evidence with read-only commands first.
- Run read-only checks freely without asking. Anything that changes the system is shown to the user for approval first, including sudo, so propose changes directly and explain what they do accurately.
- Do not run full system updates (paru -Syu) on your own initiative; tell the user when updates are pending instead.

## Known issues
- None recorded.
