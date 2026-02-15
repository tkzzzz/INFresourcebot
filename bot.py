import discord
from discord.ext import commands, tasks
import os
import logging
import asyncio
import re
import aiohttp
from bs4 import BeautifulSoup

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
# ID 68 is for SWG Infinity. 
# We target the home page specifically for this galaxy to get the "Current Spawns" table.
GALAXY_ID = "68" 
TARGET_URL = f"https://galaxyharvester.net/ghHome.py?galaxy={GALAXY_ID}"

CHECK_INTERVAL_SECONDS = 60
MAX_SEEN_ENTRIES = 200

# --- Environment Variables ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
try:
    DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", 0))
except ValueError:
    logging.error("DISCORD_CHANNEL_ID is not a valid integer.")
    DISCORD_CHANNEL_ID = 0

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!ghrep ", intents=intents)

# We use the Resource Name (e.g., "oikasis") as the unique ID
seen_resource_names = []

async def fetch_and_parse_html():
    """Fetches the Galaxy Harvester HTML and extracts resource data."""
    async with aiohttp.ClientSession() as session:
        # User-Agent is required to look like a real browser
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        try:
            async with session.get(TARGET_URL, headers=headers) as response:
                if response.status != 200:
                    logging.error(f"Failed to fetch page. Status: {response.status}")
                    return []
                html_text = await response.text()
        except Exception as e:
            logging.error(f"Network error fetching HTML: {e}")
            return []

    soup = BeautifulSoup(html_text, 'html.parser')
    resources = []

    # Strategy: Find all links that look like 'resource.py/68/name'
    # This is the most reliable way to find entries in the "Current Spawns" list
    resource_links = soup.find_all('a', href=re.compile(rf'resource\.py/{GALAXY_ID}/'))
    
    for link in resource_links:
        try:
            # name = "oikasis", href = "resource.py/68/oikasis"
            name = link.get_text(strip=True)
            href = link.get('href')
            full_link = f"https://galaxyharvester.net/{href}"
            
            # The container (td or div) holds the stats text
            container = link.find_parent('td') or link.find_parent('div')
            if not container: continue

            container_text = container.get_text(" ", strip=True)
            
            # Extract highest stat
            highest_stat = None
            highest_value = 0
            
            # Regex to find stats like "DR 900" or "OQ: 500"
            matches = re.findall(r'\b([A-Z]{2,3})[\s:]+(\d{3,4})\b', container_text)
            
            for stat, val in matches:
                val_int = int(val)
                # Filter out obvious non-stat numbers (stats are usually < 1000)
                if val_int > highest_value and val_int <= 1000:
                    highest_value = val_int
                    highest_stat = stat
            
            resources.append({
                'name': name,
                'link': full_link,
                'highest_stat': highest_stat,
                'highest_value': highest_value,
                'guid': name 
            })
            
        except Exception as e:
            logging.warning(f"Error parsing entry: {e}")
            continue

    # Reverse so we process oldest -> newest
    return resources[::-1]

@bot.event
async def on_ready():
    logging.info(f'{bot.user.name} has connected to Discord!')
    logging.info(f'Targeting Galaxy ID: {GALAXY_ID}')
    if DISCORD_CHANNEL_ID != 0:
        check_resources_task.start()

@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def check_resources_task():
    global seen_resource_names
    if DISCORD_CHANNEL_ID == 0: return

    try:
        entries = await fetch_and_parse_html()
        
        if not entries:
            logging.info("No entries found.")
            return

        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if not channel: return

        # --- STARTUP LOGIC ---
        # If this is the first run (seen list is empty), we handle the "Batch"
        if not seen_resource_names:
            logging.info("First run: handling startup batch.")
            
            # 1. Populate the seen list with EVERYTHING on the page so we don't spam 25 items
            seen_resource_names = [e['guid'] for e in entries]
            
            # 2. Pick the last 5 items to post immediately (The "Batch")
            # entries are already sorted Oldest -> Newest
            batch_to_post = entries[-5:] 
            
            logging.info(f"Posting batch of {len(batch_to_post)} recent items.")
            for entry in batch_to_post:
                await send_entry(channel, entry)
            return
        # ---------------------

        # Normal Loop: Check for items we haven't seen yet
        new_items = [e for e in entries if e['guid'] not in seen_resource_names]
        
        for entry in new_items:
            logging.info(f"New resource found: {entry['name']}")
            seen_resource_names.append(entry['guid'])
            await send_entry(channel, entry)

        # Keep memory usage low
        if len(seen_resource_names) > MAX_SEEN_ENTRIES:
            seen_resource_names = seen_resource_names[-MAX_SEEN_ENTRIES:]

    except Exception as e:
        logging.exception("Error in check loop:")

async def send_entry(channel, entry):
    """Sends the formatted message to Discord."""
    try:
        await channel.send(entry['link'])
        if entry['highest_value'] > 0:
            stat_label = entry['highest_stat'] if entry['highest_stat'] else "High Stat"
            await channel.send(f"Highest value = **{stat_label} {entry['highest_value']}**")
    except Exception as e:
        logging.error(f"Failed to send: {e}")

# --- Main Execution ---
def main():
    if not DISCORD_BOT_TOKEN:
        logging.critical("DISCORD_BOT_TOKEN not set.")
        return
    bot.run(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    main()
