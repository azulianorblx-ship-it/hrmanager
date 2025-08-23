import os
import json
import re
import threading
import asyncio
from discord.ext import commands
from discord import app_commands, Embed
from docxtpl import DocxTemplate
from docx import Document
import discord
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn
from datetime import datetime

# ---------------------------
# Setup folders and files
# ---------------------------
os.makedirs("templates", exist_ok=True)
os.makedirs("generated", exist_ok=True)
os.makedirs("dm_templates", exist_ok=True)

if not os.path.exists("templates.json"):
    with open("templates.json", "w") as f:
        json.dump({}, f)
if not os.path.exists("dm_templates.json"):
    with open("dm_templates.json", "w") as f:
        json.dump({}, f)

# ---------------------------
# Helper functions
# ---------------------------
def extract_fields(file_path):
    doc = Document(file_path)
    text = "\n".join([p.text for p in doc.paragraphs])
    fields = re.findall(r"\{\{(.*?)\}\}", text)
    return list(set(fields))

def save_template(template_name, file_path, fields):
    with open("templates.json", "r") as f:
        templates = json.load(f)
    templates[template_name] = {"file_path": file_path, "fields": fields}
    with open("templates.json", "w") as f:
        json.dump(templates, f, indent=4)

def save_dm_template(template_name, content, fields):
    with open("dm_templates.json", "r") as f:
        templates = json.load(f)
    templates[template_name] = {"content": content, "fields": fields}
    with open("dm_templates.json", "w") as f:
        json.dump(templates, f, indent=4)

BASE_URL = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "http://localhost:8000")

LOG_CHANNEL_ID = 1408784982205534239
DARK_BLUE = discord.Color.from_rgb(20, 40, 120)  # darker blue

# ---------------------------
# Bot Setup
# ---------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Slash commands synced!")

bot = MyBot()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game(name="Crown & Cabinet"))

# ---------------------------
# Announcement Buttons
# ---------------------------
class AnnouncementView(discord.ui.View):
    def __init__(self, user, embed, channel, webhook_url=None):
        super().__init__(timeout=None)
        self.user = user
        self.embed = embed
        self.channel = channel
        self.webhook_url = webhook_url

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message("You can't approve this!", ephemeral=True)
            return

        await self.channel.send(content="@everyone", embed=self.embed)
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"✅ Announcement approved by {self.user} and posted in {self.channel.mention}.")

        await interaction.response.edit_message(content="Announcement posted successfully!", view=None)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message("You can't deny this!", ephemeral=True)
            return

        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"❌ Announcement denied by {self.user}. Process cancelled.")

        await interaction.response.edit_message(content="Announcement cancelled.", view=None)

# ---------------------------
# Announcement Command
# ---------------------------
@bot.tree.command(name="announcement", description="Send an announcement using the template")
@app_commands.describe(channel="Announcement channel to post in")
async def announcement(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.send_message("Filling announcement template. Check your DMs.", ephemeral=True)

    # Load announcement template
    with open("templates.json", "r") as f:
        templates = json.load(f)
    if "announcement" not in templates:
        await interaction.followup.send("Announcement template not found. Use /update_anntemplate first.", ephemeral=True)
        return

    fields = templates["announcement"]["fields"]

    # DM user to fill in fields
    try:
        dm_channel = await interaction.user.create_dm()
        responses = {}
        def dm_check(m):
            return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

        for field in fields:
            await dm_channel.send(f"Enter value for {field}:")
            msg = await bot.wait_for("message", check=dm_check, timeout=300)
            responses[field] = msg.content
    except asyncio.TimeoutError:
        await dm_channel.send("Timeout waiting for input. Announcement cancelled.")
        return

    # Generate DOCX
    doc = DocxTemplate(templates["announcement"]["file_path"])
    doc.render(responses)
    output_docx = f"generated/{interaction.user.id}_announcement.docx"
    doc.save(output_docx)
    view_url = f"https://view.officeapps.live.com/op/embed.aspx?src={BASE_URL}/generated/{os.path.basename(output_docx)}"

    # Build embed
    subject = responses.get("Subject", "Announcement")
    full_name = responses.get("FullName", interaction.user.name)
    description = f"Please find a letter attached from {full_name}.\n[View Document]({view_url})"

    embed = Embed(
        title=f"<:logo:1408785100128387142> {subject}",
        description=description,
        color=DARK_BLUE,
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=f"Sent by {full_name}")

    # Send preview DM with Accept/Deny buttons
    await dm_channel.send("Preview your announcement below. Accept to post, Deny to cancel.", embed=embed, view=AnnouncementView(interaction.user, embed, channel))
    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"📝 Announcement preview sent to {interaction.user} for {channel.mention}.")

# ---------------------------
# FastAPI App
# ---------------------------
app = FastAPI()
app.mount("/generated", StaticFiles(directory="generated"), name="generated")
def run_api():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

# ---------------------------
# Run Bot + FastAPI
# ---------------------------
threading.Thread(target=run_api, daemon=True).start()
bot.run(os.environ['DISCORD_TOKEN'])
