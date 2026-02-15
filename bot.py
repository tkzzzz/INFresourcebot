import discord
from discord.ext import commands, tasks
import feedparser
import os
import logging
import re
import aiohttp
from datetime import datetime, timezone

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
# Use standard URLs. The User-Agent will handle the XML formatting.
RSS_FEED_URLS = [
    "https://feeds.feedburner.com/GalaxyHarvesterMineralResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterChemicalResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterFloraResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterGasResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterWaterResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterEnergyResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterCreatureResourceAdds"
]
TARGET_SERVER_NAME = "SWG Infinity"
CHECK_INTERVAL_SECONDS = 60 
MAX_SEEN_ENTRIES = 1000

# --- Environment Variables ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", 0))

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!ghrep ", intents=intents)
seen_entry_guids = []

def parse_resource_values(entry):
    try:
        if not hasattr(entry, 'content') or not entry.content: return None, None
        content_html = entry.content[0].get('value', '')
        pattern = r'([A-Z]{2})[\s:]+(\d+)(?:\s*\(\d+%\))?'
        matches = re.findall(pattern, content_html)
        if not matches: return None, None
        highest_val, highest_stat = 0, None
        for stat, val_str in matches:
            val = int(val_str)
            if val > highest_val: highest_val, highest_stat = val, stat
        return highest_stat, highest_val
    except: return None, None

@bot.event
async def on_ready():
    logging.info(f'{bot.user.name} online. Starting scan...')
    if DISCORD_CHANNEL_ID != 0 and not fetch_rss_feed_task.is_running():
        fetch_rss_feed_task.start()

@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def fetch_rss_feed_task():
    global seen_entry_guids
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel: return

    # User-Agent that identifies as an RSS reader to bypass FeedBurner landing pages
    headers = {
        'User-Agent': 'UniversalFeedParser/6.0.10 +https://github.com/kurtmckee/feedparser/',
        'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8'
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        for feed_url in RSS_FEED_URLS:
            try:
                async with session.get(feed_url, timeout=15) as response:
                    if response.status != 200:
                        logging.warning(f"Skipping {feed_url}: HTTP {response.status}")
                        continue
                    
                    raw_content = await response.text()
                    feed = feedparser.parse(raw_content)
                    
                    if feed.bozo:
                        logging.error(f"Feed error in {feed_url}: {feed.bozo_exception}")
                        continue

                    for entry in feed.entries:
                        guid = entry.get("guid", entry.link)
                        if guid not in seen_entry_guids:
                            if TARGET_SERVER_NAME.lower() in entry.title.lower():
                                logging.info(f"MATCH: {entry.title}")
                                stat, val = parse_resource_values(entry)
                                await channel.send(entry.link)
                                if stat: await channel.send(f"Highest value = **{stat} {val}**")
                            seen_entry_guids.append(guid)

            except Exception as e:
                logging.error(f"Network error for {feed_url}: {e}")

    if len(seen_entry_guids) > MAX_SEEN_ENTRIES:
        seen_entry_guids = seen_entry_guids[-MAX_SEEN_ENTRIES:]

@fetch_rss_feed_task.before_loop
async def before_fetch_rss_feed_task():
    await bot.wait_until_ready()

if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
