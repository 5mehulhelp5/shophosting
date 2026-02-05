# OpsBot Design Document

**Date:** 2026-02-02
**Status:** Approved, In Development

## Overview

OpsBot is a conversational AI assistant for ShopHosting server operations. It provides two-way communication between the admin and the server through text and voice interfaces.

## Goals

- Real-time awareness of server issues without checking dashboards
- Natural language queries about server state ("What's wrong with customer 19?")
- Voice conversations for hands-free ops
- Proactive alerts pushed to admin
- Ability to execute actions (restart containers, run playbooks)

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │           ShopHosting OpsBot            │
                    │         (Python Service)                │
                    └─────────────────────────────────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │                         │                         │
            ▼                         ▼                         ▼
    ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
    │   Telegram    │        │    Discord    │        │   Proactive   │
    │   (Text +     │        │   (Real-time  │        │    Alerts     │
    │ Voice Msgs)   │        │    Voice)     │        │   (Push)      │
    └───────────────┘        └───────────────┘        └───────────────┘
```

## Components

### Communication Channels

| Channel | Use Case |
|---------|----------|
| Telegram text | Quick queries, on-the-go |
| Telegram voice msg | Speak question, get voice reply |
| Discord voice | Real-time conversation, hands-free |
| Proactive alerts | Server pushes critical issues to both |

### Technology Stack

| Component | Technology | Cost |
|-----------|------------|------|
| Text chat | Telegram Bot API | Free |
| Voice chat | Discord + Whisper + Piper | Free |
| AI brain | Ollama (Mistral 7B) | Free |
| Hosting | Existing server | Free |

### AI Tools

**Safe (no confirmation):**
- `list_customers()` - List all customers
- `get_container_status(customer_id)` - Check container state
- `get_health_score(customer_id)` - Get performance score
- `get_recent_logs(customer_id, service, lines)` - View logs
- `get_metrics(customer_id)` - CPU, memory, disk usage
- `list_active_alerts()` - Show current alerts

**Requires confirmation:**
- `restart_container(customer_id)` - Restart customer stack
- `clear_cache(customer_id)` - Clear Redis/Varnish
- `run_playbook(name, customer_id)` - Execute automation

**Blocked:**
- Delete customer data
- Modify billing
- Access credentials/passwords

## File Structure

```
/opt/shophosting/opsbot/
├── bot.py                 # Main entry point
├── config.py              # Settings
├── channels/
│   ├── telegram_bot.py    # Telegram integration
│   └── discord_bot.py     # Discord voice integration
├── ai/
│   ├── ollama_client.py   # Chat with Ollama
│   ├── tools.py           # Tool definitions
│   └── prompts.py         # System prompts
├── voice/
│   ├── whisper_stt.py     # Speech-to-text
│   └── piper_tts.py       # Text-to-speech
├── server_tools/
│   ├── containers.py      # Docker operations
│   ├── logs.py            # Log reading
│   ├── metrics.py         # Prometheus queries
│   ├── playbooks.py       # Automation playbooks
│   └── alerts.py          # Alert management
├── proactive/
│   └── alert_pusher.py    # Push alerts to channels
└── requirements.txt
```

## Implementation Phases

### Phase 1 - Foundation
- Create directory structure
- Set up Telegram bot (text only)
- Connect to Ollama with basic tools
- Test basic queries

### Phase 2 - Server Tools
- Implement read-only tools
- Implement action tools with confirmation
- Wire up proactive alerts

### Phase 3 - Voice
- Install Whisper + Piper
- Add Telegram voice message support
- Set up Discord voice channel support

### Phase 4 - Polish
- Wake word detection
- Tune system prompts
- Conversation memory

## Notes

- This is a separate product from ShopHosting (added to .gitignore)
- Uses existing Ollama installation (Mistral 7B)
- Can upgrade to larger model (qwen2.5:32b) if needed
