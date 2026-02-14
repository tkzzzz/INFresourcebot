# SR2 Resource Bot - Claude Documentation

## Project Overview
Discord bot that monitors Galaxy Harvester RSS feeds for Star Wars Galaxies "Sentinels Republic 2" server resource spawns and posts notifications with enhanced value highlighting.

## Key Features
- Monitors RSS feed every 5 minutes: `https://feeds.feedburner.com/GalaxyHarvesterResourceActivity`
- Filters entries for "Sentinels Republic 2" server
- Posts Discord notifications with URL auto-preview
- **Enhanced Feature**: Parses resource stats and highlights highest value with bold formatting
- Prevents duplicate notifications using seen entries list (max 200)

## Technical Implementation

### Resource Value Parsing
The bot extracts resource statistics from RSS feed content using regex pattern matching:
- Pattern: `([A-Z]{2}):\s*(\d+)\s*\(\d+%\)` 
- Matches stats like: DR: 780 (78%), PE: 949 (95%), etc.
- Identifies highest value across all resource types (DR, MA, OQ, SR, UT, FL, PE, etc.)

### Discord Message Format
1. Posts the Galaxy Harvester URL (Discord auto-previews)
2. Follows with: `Highest value = **PE 949**` (bold formatting)

## Environment Variables
- `DISCORD_BOT_TOKEN`: Bot authentication token
- `DISCORD_CHANNEL_ID`: Target Discord channel ID for notifications

## Dependencies (requirements.txt)
- discord.py>=2.3.0
- feedparser>=6.0.0  
- aiohttp>=3.8.0

## Deployment
- **Platform**: Railway (auto-deploys from GitHub pushes)
- **Repository**: https://github.com/tkzzzz/sr2resourcebot
- **Branch**: main

## Configuration Constants
- `CHECK_INTERVAL_SECONDS = 300` (5 minutes)
- `MAX_SEEN_ENTRIES = 200`
- `TARGET_SERVER_NAME = "Sentinels Republic 2"`

## Key Functions
- `parse_resource_values(entry)`: Extracts and finds highest resource stat
- `fetch_rss_feed_task()`: Main periodic RSS monitoring loop
- `before_fetch_rss_feed_task()`: Pre-populates seen entries to prevent spam

## Testing Commands
```bash
# Install dependencies
pip3 install -r requirements.txt

# Test locally (set environment variables first)
DISCORD_BOT_TOKEN="token" DISCORD_CHANNEL_ID="id" python bot.py

# Syntax check
python -m py_compile bot.py
```

## Recent Changes
- Added regex-based resource value parsing
- Enhanced Discord messages with highest value highlighting
- Improved logging for resource value detection
- Maintained backward compatibility with existing functionality