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
from datetime import datetime, timezone
import aiohttp

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
# Role IDs
# ---------------------------
ROLE_ANNOUNCEMENT = 1410856956629090366
ROLE_DOCUMENT_MANAGER = 1410856963507617852
ROLE_DM_PERMISSIONS = 1410857218303070281

# ---------------------------
# Helper for role checking
# ---------------------------
def has_role(user: discord.Member, role_id: int):
    return any(role.id == role_id for role in user.roles)

async def require_role(interaction: discord.Interaction, role_id: int):
    if not has_role(interaction.user, role_id) and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You do not have permission to use this command.", ephemeral=True
        )
        return False
    return True

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
GUILD_ID = int(os.environ.get("GUILD_ID", 0))
if not GUILD_ID:
    raise ValueError("GUILD_ID not set in environment variables")

LOG_CHANNEL_ID = 1411299414869282847
DARK_BLUE = discord.Color.from_rgb(20, 40, 120)

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
        await self.tree.sync(guild=discord.Object(id=GUILD_ID))
        print("Slash commands synced!")

bot = MyBot()

async def log_action(bot, message: str):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        try:
            await channel.send(f"📘 **Log:** {message}")
        except:
            print("[WARN] Could not send log message")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game(name="Thornvale Academy"))


# ---------------------------
# DOCX Commands
# ---------------------------
@bot.tree.command(name="add_template", description="Add a new DOCX template", guild=discord.Object(id=GUILD_ID))
async def add_template(interaction: discord.Interaction):
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        return
    await interaction.response.send_message("Upload your DOCX template as a reply in this channel.")

    def check(msg):
        return msg.author == interaction.user and msg.attachments and msg.channel == interaction.channel

    try:
        msg = await bot.wait_for("message", check=check, timeout=120)
    except:
        await interaction.followup.send("Timeout or error waiting for file.")
        return

    file = msg.attachments[0]
    await interaction.followup.send("What should the template name be?")

    try:
        name_msg = await bot.wait_for(
            "message",
            check=lambda m: m.author == interaction.user and m.channel == interaction.channel,
            timeout=60
        )
    except:
        await interaction.followup.send("Timeout or error waiting for template name.")
        return

    template_name = name_msg.content
    file_ext = os.path.splitext(file.filename)[1]
    file_path = f"templates/{interaction.user.id}_{int(datetime.now().timestamp())}{file_ext}"
    await file.save(file_path)
    fields = extract_fields(file_path)
    save_template(template_name, file_path, fields)
    await interaction.followup.send(f"Template '{template_name}' added with fields: {fields}")
    await log_action(bot, f"{interaction.user} added template '{template_name}'")

@bot.tree.command(name="list_docx_templates", description="List all DOCX templates", guild=discord.Object(id=GUILD_ID))
async def list_docx_templates(interaction: discord.Interaction):
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        return
    with open("templates.json", "r") as f:
        templates = json.load(f)
    if not templates:
        await interaction.response.send_message("No DOCX templates found.", ephemeral=True)
        return
    await interaction.response.send_message("📑 DOCX Templates:\n" + "\n".join(templates.keys()), ephemeral=True)

@bot.tree.command(name="generate_document", description="Generate a document from a template", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(template_name="Name of the template to use")
async def generate_document(interaction: discord.Interaction, template_name: str):
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        return
    await interaction.response.send_message(f"Generating document for template '{template_name}'. Check your DMs!", ephemeral=True)

    with open("templates.json", "r") as f:
        templates = json.load(f)
    if template_name not in templates:
        await interaction.followup.send("Template not found.", ephemeral=True)
        return

    fields = templates[template_name]["fields"]
    try:
        dm_channel = await interaction.user.create_dm()
        await dm_channel.send(f"Please provide the following fields: {fields}")
    except:
        await interaction.followup.send("Cannot DM you. Check privacy settings.", ephemeral=True)
        return

    responses = {}
    def dm_check(m):
        return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

    for field in fields:
        await dm_channel.send(f"Enter value for {field}:")
        try:
            msg = await bot.wait_for("message", check=dm_check, timeout=300)
            responses[field] = msg.content
        except asyncio.TimeoutError:
            await dm_channel.send("Timeout waiting for input.")
            return

    doc = DocxTemplate(templates[template_name]["file_path"])
    doc.render(responses)
    output_docx = f"generated/{interaction.user.id}_{template_name}.docx"
    doc.save(output_docx)

    view_url = f"https://view.officeapps.live.com/op/embed.aspx?src={BASE_URL}/generated/{os.path.basename(output_docx)}"
    await dm_channel.send(f"Here is your document (viewable in browser): {view_url}")
    await log_action(bot, f"{interaction.user} generated document from '{template_name}'")

import json
import aiohttp
import asyncio
import discord

# ---------------------------
# DM Template Commands
# ---------------------------
@bot.tree.command(name="create_dm_template", description="Create a new DM template", guild=discord.Object(id=GUILD_ID))
async def create_dm_template(interaction: discord.Interaction):
    if not await require_role(interaction, ROLE_DM_PERMISSIONS):
        return
    await interaction.response.send_message("Please check your DMs to create a new DM template.", ephemeral=True)
    dm_channel = await interaction.user.create_dm()
    await dm_channel.send("Send the content of the DM template. Use {{field}} placeholders for variables.")

    def check(m):
        return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

    try:
        msg = await bot.wait_for("message", check=check, timeout=600)
        content = msg.content
        fields = list(set(re.findall(r"\{\{(.*?)\}\}", content)))
        await dm_channel.send("What should the template name be?")
        name_msg = await bot.wait_for("message", check=check, timeout=120)
        template_name = name_msg.content
        save_dm_template(template_name, content, fields)
        await dm_channel.send(f"DM template '{template_name}' saved with fields: {fields}")
        await log_action(bot, f"{interaction.user} created DM template '{template_name}'")
    except asyncio.TimeoutError:
        await dm_channel.send("Timeout. Template creation cancelled.")

@bot.tree.command(name="list_dm_templates", description="List all DM templates", guild=discord.Object(id=GUILD_ID))
async def list_dm_templates(interaction: discord.Interaction):
    if not await require_role(interaction, ROLE_DM_PERMISSIONS):
        return
    with open("dm_templates.json", "r") as f:
        templates = json.load(f)
    if not templates:
        await interaction.response.send_message("No DM templates found.", ephemeral=True)
        return
    await interaction.response.send_message("📑 DM Templates:\n" + "\n".join(templates.keys()), ephemeral=True)

@bot.tree.command(name="send_dm", description="Send a DM to a user using a saved template", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(template_name="The DM template to use", user="User to send the DM to")
async def send_dm(interaction: discord.Interaction, template_name: str, user: discord.User):
    if not await require_role(interaction, ROLE_DM_PERMISSIONS):
        return
    if not interaction.user.guild_permissions.manage_messages and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return

    with open("dm_templates.json", "r") as f:
        templates = json.load(f)
    if template_name not in templates:
        await interaction.response.send_message("❌ Template not found.", ephemeral=True)
        return

    template = templates[template_name]
    fields = template["fields"]
    content = template["content"]

    dm_channel = await interaction.user.create_dm()
    await dm_channel.send(f"Please provide the following fields for template '{template_name}': {fields}")

    responses = {}
    def dm_check(m):
        return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

    for field in fields:
        await dm_channel.send(f"Enter value for {field}:")
        try:
            msg = await bot.wait_for("message", check=dm_check, timeout=300)
            responses[field] = msg.content
        except asyncio.TimeoutError:
            await dm_channel.send("Timeout waiting for input.")
            return

    final_message = content
    for k, v in responses.items():
        final_message = final_message.replace(f"{{{{{k}}}}}", v)

    try:
        target_dm = await user.create_dm()
        await target_dm.send(final_message)
        await interaction.response.send_message(f"✅ DM sent to {user.display_name}.", ephemeral=True)
        await log_action(bot, f"{interaction.user} sent DM to {user} using template '{template_name}'")
    except:
        await interaction.response.send_message("❌ Could not send DM (user may have DMs closed).", ephemeral=True)

# ---------------------------
# Embed Template Handling
# ---------------------------
EMBED_TEMPLATES_FILE = "embed_templates.json"
if not os.path.exists(EMBED_TEMPLATES_FILE):
    with open(EMBED_TEMPLATES_FILE, "w") as f:
        json.dump({}, f)

def save_embed_template(name, data):
    with open(EMBED_TEMPLATES_FILE, "r") as f:
        templates = json.load(f)
    templates[name] = data
    with open(EMBED_TEMPLATES_FILE, "w") as f:
        json.dump(templates, f, indent=4)

def load_embed_templates():
    with open(EMBED_TEMPLATES_FILE, "r") as f:
        return json.load(f)


# ---------------------------
# Announcement Buttons
# ---------------------------
class AnnouncementView(discord.ui.View):
    def __init__(self, user, embed, channel):
        super().__init__(timeout=None)
        self.user = user
        self.embed = embed
        self.channel = channel

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
@bot.tree.command(name="announcement", description="Send an announcement using the template", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(channel="Announcement channel to post in")
async def announcement(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await require_role(interaction, ROLE_ANNOUNCEMENT):
        return
    await interaction.response.send_message("Filling announcement template. Check your DMs.", ephemeral=True)
    with open("templates.json", "r") as f:
        templates = json.load(f)
    if "announcement" not in templates:
        await interaction.followup.send("Announcement template not found. Use /update_anntemplate first.", ephemeral=True)
        return
    fields = templates["announcement"]["fields"]

    try:
        dm_channel = await interaction.user.create_dm()
        responses = {}
        def dm_check(m): return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)
        for field in fields:
            await dm_channel.send(f"Enter value for {field}:")
            msg = await bot.wait_for("message", check=dm_check, timeout=300)
            responses[field] = msg.content
    except asyncio.TimeoutError:
        await dm_channel.send("Timeout waiting for input. Announcement cancelled.")
        return

    doc = DocxTemplate(templates["announcement"]["file_path"])
    doc.render(responses)
    output_docx = f"generated/{interaction.user.id}_announcement.docx"
    doc.save(output_docx)
    view_url = f"https://view.officeapps.live.com/op/embed.aspx?src={BASE_URL}/generated/{os.path.basename(output_docx)}"

    subject = responses.get("Subject", "Announcement")
    full_name = responses.get("FullName", interaction.user.name)
    description = f"Please find a letter attached from {full_name}.\n[View Document]({view_url})"
    embed = Embed(
        title=f"<:TVALogo:1408794388129120316> {subject}",
        description=description,
        color=DARK_BLUE,
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=f"Sent by {full_name}")

    await dm_channel.send("Preview your announcement below. Accept to post, Deny to cancel.", embed=embed, view=AnnouncementView(interaction.user, embed, channel))
    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"📝 Announcement preview sent to {interaction.user} for {channel.mention}.")

# ---------------------------
# Update Announcement Template Command
# ---------------------------
@bot.tree.command(name="update_anntemplate", description="Update the announcement DOCX template", guild=discord.Object(id=GUILD_ID))
async def update_anntemplate(interaction: discord.Interaction):
    if not await require_role(interaction, ROLE_ANNOUNCEMENT):
        return
    await interaction.response.send_message("Upload your new announcement DOCX template as a reply in this channel.", ephemeral=True)

    def check(msg):
        return msg.author == interaction.user and msg.attachments and msg.channel == interaction.channel

    try:
        msg = await bot.wait_for("message", check=check, timeout=120)
    except asyncio.TimeoutError:
        await interaction.followup.send("Timeout waiting for file.", ephemeral=True)
        return

    file = msg.attachments[0]
    file_ext = os.path.splitext(file.filename)[1]
    file_path = f"templates/{interaction.user.id}_announcement{file_ext}"
    await file.save(file_path)

    fields = extract_fields(file_path)
    save_template("announcement", file_path, fields)

    await interaction.followup.send(f"Announcement template updated with fields: {fields}", ephemeral=True)
    await log_action(bot, f"{interaction.user} updated announcement template")

@bot.tree.command(name="msg", description="Send a plain message to a channel", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(
    channel="Channel where the message will be sent",
    message="The message text to send"
)
async def msg(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    # ✅ Require role check
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        await interaction.response.send_message("❌ You don’t have permission to use this.", ephemeral=True)
        return

    try:
        await channel.send(message)
        await interaction.response.send_message(f"✅ Message sent to {channel.mention}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to send message: {e}", ephemeral=True)

@bot.tree.command(name="image", description="Send an image or file to a channel", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(
    channel="Channel where the file will be sent",
    file="The file to send"
)
async def image(interaction: discord.Interaction, channel: discord.TextChannel, file: discord.Attachment):
    # ✅ Require role check
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        await interaction.response.send_message("❌ You don’t have permission to use this.", ephemeral=True)
        return

    try:
        # Convert the attachment to a discord.File
        discord_file = await file.to_file()
        await channel.send(file=discord_file)
        await interaction.response.send_message(f"✅ File sent to {channel.mention}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to send file: {e}", ephemeral=True)

# ---------------------------
# Embed Commands
# ---------------------------
@bot.tree.command(name="create_embedtemplate", description="Create a new embed template", guild=discord.Object(id=GUILD_ID))
async def create_embedtemplate(interaction: discord.Interaction):
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        return
    await interaction.response.send_message("Check your DMs to create a new embed template.", ephemeral=True)
    dm_channel = await interaction.user.create_dm()

    fields = {
        "name": "Template name (no spaces)",
        "title": "Embed title",
        "description": "Embed description",
        "footer": "Embed footer (optional)",
        "color": "Embed color (hex, e.g. #3498db) (optional)",
        "image_url": "Image URL (optional)",
        "thumbnail_url": "Thumbnail URL (optional)",
        "channel_id": "Target channel ID (copy with Discord dev mode)",
        "ping": "Ping (e.g. @everyone, @here, or role mention, or 'none')"
    }

    responses = {}
    def check(m): return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

    for key, prompt in fields.items():
        await dm_channel.send(f"{prompt} (type 'skip' to leave blank)")
        try:
            msg = await bot.wait_for("message", check=check, timeout=600)
            responses[key] = "" if msg.content.lower() == "skip" else msg.content
        except asyncio.TimeoutError:
            await dm_channel.send("Timeout. Template creation cancelled.")
            return

    color = DARK_BLUE
    if responses.get("color"):
        try:
            color = discord.Color(int(responses["color"].replace("#", ""), 16))
        except:
            color = DARK_BLUE

    channel_id = None
    if responses.get("channel_id"):
        digits = re.sub(r"\D", "", responses["channel_id"])
        channel_id = int(digits) if digits else None

    data = {
        "title": responses["title"],
        "description": responses["description"],
        "footer": responses.get("footer", ""),
        "color": color.value,
        "image_url": responses.get("image_url", ""),
        "thumbnail_url": responses.get("thumbnail_url", ""),
        "channel_id": channel_id,
        "ping": responses.get("ping", "none")
    }

    save_embed_template(responses["name"], data)
    await dm_channel.send(f"✅ Embed template '{responses['name']}' saved!")
    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"📦 {interaction.user} created embed template '{responses['name']}'.")

@bot.tree.command(name="list_embedtemplates", description="List all saved embed templates", guild=discord.Object(id=GUILD_ID))
async def list_embedtemplates(interaction: discord.Interaction):
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        return
    templates = load_embed_templates()
    if not templates:
        await interaction.response.send_message("No embed templates found.", ephemeral=True)
        return
    await interaction.response.send_message("📑 Embed Templates:\n" + "\n".join(templates.keys()), ephemeral=True)

# store ongoing embed sessions
active_embeds = {}

@bot.tree.command(name="embed", description="Create a custom embed interactively", guild=discord.Object(id=GUILD_ID))
async def embed(interaction: discord.Interaction):
    # ensure only staff can use
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        await interaction.response.send_message("❌ You do not have permission to use this.", ephemeral=True)
        return

    await interaction.response.send_message("📩 Check your DMs to build your embed.", ephemeral=True)

    user = interaction.user
    dm = await user.create_dm()

    questions = [
        ("title", "Enter the **embed title** (or type `skip`)"),
        ("description", "Enter the **embed description** (or type `skip`)"),
        ("footer", "Enter the **embed footer** (or type `skip`)"),
        ("color", "Enter the **embed color** (hex, e.g. #3498db) (or type `skip`)"),
        ("image_url", "Enter the **image URL** (or type `skip`)"),
        ("thumbnail_url", "Enter the **thumbnail URL** (or type `skip`)"),
        ("ping", "Enter a ping (`@everyone`, `@here`, role mention, or `none`)"),
        ("channel", "State the channel id. REQUIRED.")
    ]

    answers = {}

    def check(m):
        return m.author.id == user.id and isinstance(m.channel, discord.DMChannel)

    for field, prompt in questions:
        await dm.send(prompt)

        try:
            msg = await bot.wait_for("message", timeout=120.0, check=check)
        except asyncio.TimeoutError:
            await dm.send("⏰ Timed out. Please restart `/embed`.")
            return

        if msg.content.lower() == "skip":
            answers[field] = None
        elif field == "channel":
            try:
                answers[field] = int(msg.content.strip())
            except ValueError:
                await dm.send("❌ Invalid channel ID. Please restart `/embed`.")
                return
        else:
            answers[field] = msg.content

    # Build embed
    color = DARK_BLUE
    if answers.get("color"):
        try:
            color = discord.Color(int(answers["color"].replace("#", ""), 16))
        except:
            pass

    embed_obj = discord.Embed(
        title=answers.get("title") or "",
        description=answers.get("description") or "",
        color=color
    )

    if answers.get("footer"):
        embed_obj.set_footer(text=answers["footer"])
    if answers.get("image_url"):
        embed_obj.set_image(url=answers["image_url"])
    if answers.get("thumbnail_url"):
        embed_obj.set_thumbnail(url=answers["thumbnail_url"])

    # Find channel
    target_channel = None
    if answers.get("channel"):
        target_channel = interaction.guild.get_channel(answers["channel"])


    if not target_channel:
        await dm.send("❌ No valid channel provided. Cancelled.")
        return

    # Send embed
    ping_text = "" if not answers.get("ping") or answers["ping"].lower() == "none" else answers["ping"]
    await target_channel.send(content=ping_text, embed=embed_obj)

    await dm.send(f"✅ Embed successfully sent to {target_channel.mention}")

# ---------------------------
# Moderation Commands
# ---------------------------
from datetime import timedelta

@bot.tree.command(name="kick", description="Kick a user from the server", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="User to kick", reason="Reason for the kick")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("❌ You don’t have permission to kick members.", ephemeral=True)
        return
    try:
        await user.kick(reason=reason)
        await interaction.response.send_message(f"✅ {user.mention} has been kicked. Reason: {reason}", ephemeral=True)
        await log_action(bot, f"{interaction.user} kicked {user} ({reason})")
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to kick {user}. Error: {e}", ephemeral=True)


@bot.tree.command(name="ban", description="Ban a user from the server", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="User to ban", reason="Reason for the ban")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("❌ You don’t have permission to ban members.", ephemeral=True)
        return
    try:
        await user.ban(reason=reason)
        await interaction.response.send_message(f"✅ {user.mention} has been banned. Reason: {reason}", ephemeral=True)
        await log_action(bot, f"{interaction.user} banned {user} ({reason})")
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to ban {user}. Error: {e}", ephemeral=True)


# We’ll store warnings in a JSON file
WARN_FILE = "warnings.json"
if not os.path.exists(WARN_FILE):
    with open(WARN_FILE, "w") as f:
        json.dump({}, f)

def load_warnings():
    with open(WARN_FILE, "r") as f:
        return json.load(f)

def save_warnings(data):
    with open(WARN_FILE, "w") as f:
        json.dump(data, f, indent=4)


@bot.tree.command(name="warn", description="Warn a user", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="User to warn", reason="Reason for the warning")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ You don’t have permission to warn members.", ephemeral=True)
        return

    warnings = load_warnings()
    user_id = str(user.id)

    if user_id not in warnings:
        warnings[user_id] = []
    warnings[user_id].append({"moderator": str(interaction.user), "reason": reason, "time": str(datetime.utcnow())})
    save_warnings(warnings)

    try:
        await user.send(f"⚠️ You have been warned in **{interaction.guild.name}**. Reason: {reason}")
    except:
        pass  # User might have DMs closed

    await interaction.response.send_message(f"✅ {user.mention} has been warned. Reason: {reason}", ephemeral=True)
    await log_action(bot, f"{interaction.user} warned {user} ({reason})")


@bot.tree.command(name="timeout", description="Timeout a user for a given duration", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="User to timeout", duration="Duration in minutes", reason="Reason for the timeout")
async def timeout(interaction: discord.Interaction, user: discord.Member, duration: int, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("❌ You don’t have permission to timeout members.", ephemeral=True)
        return
    try:
        until = datetime.utcnow() + timedelta(minutes=duration)
        await user.timeout(until, reason=reason)
        await interaction.response.send_message(
            f"✅ {user.mention} has been timed out for {duration} minutes. Reason: {reason}", ephemeral=True
        )
        await log_action(bot, f"{interaction.user} timed out {user} ({reason}, {duration}m)")
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to timeout {user}. Error: {e}", ephemeral=True)

# ---------------------------
# Modmail System (with Attachments)
# ---------------------------

MODMAIL_CATEGORY_ID = 1408849860202860594  # category where tickets go
SENIOR_LEADERSHIP_ROLE = 1410288467782533270  # role allowed to see tickets
MODMAIL_FILE = "modmail_tickets.json"

if not os.path.exists(MODMAIL_FILE):
    with open(MODMAIL_FILE, "w") as f:
        json.dump({}, f)

def load_modmail():
    with open(MODMAIL_FILE, "r") as f:
        return json.load(f)

def save_modmail(data):
    with open(MODMAIL_FILE, "w") as f:
        json.dump(data, f, indent=4)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # ---------------------------
    # User DMs the bot
    # ---------------------------
    if isinstance(message.channel, discord.DMChannel):
        tickets = load_modmail()
        user_id = str(message.author.id)
        guild = bot.get_guild(GUILD_ID)

        # Only open ticket if user says HELP
        if message.content.strip().upper() == "HELP" and user_id not in tickets:
            category = guild.get_channel(MODMAIL_CATEGORY_ID)

            # Create private ticket channel
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.get_role(SENIOR_LEADERSHIP_ROLE): discord.PermissionOverwrite(view_channel=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }

            channel = await category.create_text_channel(name=f"ticket-{message.author.name}", overwrites=overwrites)


            tickets[user_id] = channel.id
            save_modmail(tickets)

            await message.channel.send("📬 Thank you! Your query has been submitted. Senior Leadership will contact you shortly.")
            await channel.send(f"📩 New Modmail from {message.author.mention} ({message.author.id})")

        else:
            channel = guild.get_channel(tickets[user_id])

        if channel:
            embed = discord.Embed(description=message.content or "*[No text]*", color=DARK_BLUE)
            embed.set_author(name=f"{message.author}", icon_url=message.author.display_avatar.url)
            await channel.send(embed=embed)

            # Forward attachments
            for attachment in message.attachments:
                await channel.send(f"📎 Attachment from {message.author}:", file=await attachment.to_file())


    # ---------------------------
    # Staff replies in ticket channel with /r
    # ---------------------------
    elif message.channel.category_id == MODMAIL_CATEGORY_ID and message.content.startswith("/r "):
        tickets = load_modmail()
        reply_text = message.content[3:].strip()

        for user_id, channel_id in tickets.items():
            if channel_id == message.channel.id:
                user = await bot.fetch_user(int(user_id))

                embed = discord.Embed(description=reply_text or "*[No text]*", color=DARK_BLUE)
                embed.set_author(name=f"{message.author} (Senior Leadership)", icon_url=message.author.display_avatar.url)

                try:
                    await user.send(embed=embed)

                    # Forward attachments if any
                    for attachment in message.attachments:
                        await user.send(file=await attachment.to_file())

                    await message.channel.send(f"✅ Reply sent to {user.mention}")
                except:
                    await message.channel.send("❌ Could not DM user.")
                break


# ---------------------------
# Slash command: close ticket
# ---------------------------
@bot.tree.command(name="close", description="Close a modmail ticket", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="User whose ticket you want to close")
async def close_modmail(interaction: discord.Interaction, user: discord.User):
    tickets = load_modmail()
    user_id = str(user.id)

    if user_id not in tickets:
        await interaction.response.send_message("❌ That user does not have an open ticket.", ephemeral=True)
        return

    channel_id = tickets[user_id]
    channel = interaction.guild.get_channel(channel_id)

    if channel:
        await channel.delete()

    del tickets[user_id]
    save_modmail(tickets)

    try:
        dm = await user.create_dm()
        await dm.send("📪 Your modmail ticket has been closed by Senior Leadership. Thank you for reaching out.")
    except:
        pass

    await interaction.response.send_message(f"✅ Closed modmail ticket for {user.mention}.", ephemeral=True)
    await log_action(bot, f"{interaction.user} closed modmail for {user}")

@bot.tree.command(
    name="send_jsonfile_dynamic",
    description="Send a JSON message with components v2 attachments",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    channel="Channel to send the JSON message to",
    json_file="Upload the Discohook JSON file"
)
async def send_jsonfile_dynamic(interaction: discord.Interaction, channel: discord.TextChannel, json_file: discord.Attachment):
    # ✅ Role check
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        return

    # Defer to give user time
    await interaction.response.defer(ephemeral=True)

    try:
        # Load JSON
        raw = await json_file.read()
        payload = json.loads(raw.decode("utf-8"))

        # Find attachment:// references
        attachment_filenames = set(re.findall(r"attachment://([\w\-. ()]+)", json.dumps(payload)))
        uploaded_files = {}

        if attachment_filenames:
            dm = await interaction.user.create_dm()
            await dm.send(
                f"Your JSON references the following files: {', '.join(attachment_filenames)}.\n"
                "Please upload them in a single message here within 5 minutes."
            )

            def normalize(name):
                return re.sub(r"[\s_]", "", name.lower())

            def check(m):
                return (
                    m.author.id == interaction.user.id and
                    any(normalize(a.filename) in [normalize(fn) for fn in attachment_filenames] for a in m.attachments)
                )


            try:
                msg = await bot.wait_for("message", check=check, timeout=300)
                for a in msg.attachments:
                    if a.filename in attachment_filenames:
                        uploaded_files[a.filename] = a
            except asyncio.TimeoutError:
                await interaction.followup.send("❌ Timeout waiting for required attachments. Command cancelled.")
                return

        # Build form-data request
        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps(payload))

        for i, filename in enumerate(uploaded_files):
            f = uploaded_files[filename]
            data = await f.read()
            form.add_field(
                f"files[{i}]",
                data,
                filename=f.filename,
                content_type=f.content_type or "application/octet-stream"
            )

        # Send to Discord API
        url = f"https://discord.com/api/v10/channels/{channel.id}/messages"
        headers = {"Authorization": f"Bot {os.environ['DISCORD_TOKEN']}"}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=form) as resp:
                if resp.status in (200, 201):
                    await interaction.followup.send(f"✅ JSON message sent to {channel.mention}")
                else:
                    err = await resp.text()
                    await interaction.followup.send(f"❌ Failed ({resp.status}): {err}")

    except Exception as e:
        await interaction.followup.send(f"❌ Error processing JSON file: {e}")

@bot.tree.command(
    name="embed",
    description="Create a custom container interactively",
    guild=discord.Object(id=GUILD_ID)
)
async def embed(interaction: discord.Interaction):
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        await interaction.response.send_message("❌ You do not have permission to use this.", ephemeral=True)
        return

    await interaction.response.send_message("📩 Check your DMs to build your container.", ephemeral=True)
    user = interaction.user
    dm = await user.create_dm()

    questions = [
        ("title", "Enter the **title** (or type `skip`)"),
        ("description", "Enter the **description** (or type `skip`)"),
        ("footer", "Enter the **footer** (or type `skip`)"),
        ("image_url", "Enter the **image URL** (or type `skip`)"),
        ("thumbnail_url", "Enter the **thumbnail URL** (or type `skip`)"),
        ("ping", "Enter a ping (`@everyone`, `@here`, role mention, or `none`)"),
        ("channel", "State the channel id. REQUIRED.")
    ]

    answers = {}

    def check(m):
        return m.author.id == user.id and isinstance(m.channel, discord.DMChannel)

    for field, prompt in questions:
        await dm.send(prompt)
        try:
            msg = await bot.wait_for("message", timeout=120.0, check=check)
        except asyncio.TimeoutError:
            await dm.send("⏰ Timed out. Please restart `/embed`.")
            return

        if msg.content.lower() == "skip":
            answers[field] = None
        elif field == "channel":
            try:
                answers[field] = int(msg.content.strip())
            except ValueError:
                await dm.send("❌ Invalid channel ID. Please restart `/embed`.")
                return
        else:
            answers[field] = msg.content

    # Build payload for container message
    components = [
        {
            "type": 17,
            "components": [
                {
                    "type": 9,
                    "components": [
                        {
                            "type": 10,
                            "content": f"**{answers.get('title') or ''}**\n{answers.get('description') or ''}"
                        }
                    ],
                    "accessory": None  # Could add a button if desired
                }
            ]
        }
    ]

    if answers.get("image_url"):
        components[0]["components"].append({
            "type": 12,
            "items": [{"media": {"url": answers["image_url"]}}]
        })

    payload = {
        "flags": 0,
        "components": components
    }

    if answers.get("ping") and answers["ping"].lower() != "none":
        payload["content"] = answers["ping"]

    # Send via API
    url = f"https://discord.com/api/v10/channels/{answers['channel']}/messages"
    headers = {
        "Authorization": f"Bot {os.environ['DISCORD_TOKEN']}",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            text = await resp.text()
            if resp.status in (200, 201):
                await dm.send(f"✅ Container successfully sent to <#{answers['channel']}>")
            else:
                await dm.send(f"❌ Failed to send container: {resp.status} {text}")

@bot.tree.command(
    name="staffjoin",
    description="Trigger staff join.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(channel="Channel to send the container to")
async def send_sample_container(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        return

    await interaction.response.defer(ephemeral=True)

    # Discohook-style payload
    payload = {
  "flags": 32768,
  "components": [
    {
      "type": 10,
      "content": "@everyone"
    },
    {
      "type": 17,
      "components": [
        {
          "type": 12,
          "items": [
            {
              "media": {
                "url": "https://media.discordapp.net/attachments/1411299414869282847/1411759919241363527/Banners_11.png?ex=68b5d361&is=68b481e1&hm=95ceabba5571b5baf6bad6f9efe6c89ace8c0f66e659b9c5f4e043b9861c64fd&=&format=webp&quality=lossless"
              }
            }
          ]
        },
        {
          "type": 9,
          "components": [
            {
              "type": 10,
              "content": "# Staff Join\nGreeting team, it is now time for you to begin joining our campus in preparation for the session to begin. A reminder to equip your lanyard, radio and hivis jacket if required. If you have claimed a classroom, please setup that classroom as you desire. \n\nFailure to attend when you have claimed a classroom or duties will result in an immediate strike from the Human Resources Department."
            }
          ],
          "accessory": {
            "type": 2,
            "style": 5,
            "label": "Join!",
            "url": "https://www.roblox.com/games/83329354034194/Thornvale",
          }
        }
      ]
    }
  ]
}
  

    url = f"https://discord.com/api/v10/channels/{channel.id}/messages"
    headers = {
        "Authorization": f"Bot {os.environ['DISCORD_TOKEN']}",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            text = await resp.text()
            if resp.status in (200, 201):
                await interaction.followup.send(f"✅ Container sent to {channel.mention}")
            else:
                await interaction.followup.send(f"❌ Failed to send container: {resp.status} {text}")
                
@bot.tree.command(
    name="briefing",
    description="Trigger staff weekly briefing.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(channel="Channel to send the container to")
async def send_sample_container(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await require_role(interaction, ROLE_DOCUMENT_MANAGER):
        return

    await interaction.response.defer(ephemeral=True)

    # Discohook-style payload
    payload = {
  "flags": 32768,
  "components": [
    {
      "type": 10,
      "content": "@everyone"
    },
    {
      "type": 17,
      "components": [
        {
          "type": 12,
          "items": [
            {
              "media": {
                "url": "https://media.discordapp.net/attachments/1411299414869282847/1411759919241363527/Banners_11.png?ex=68b5d361&is=68b481e1&hm=95ceabba5571b5baf6bad6f9efe6c89ace8c0f66e659b9c5f4e043b9861c64fd&=&format=webp&quality=lossless"
              }
            }
          ]
        },
        {
          "type": 9,
          "components": [
            {
              "type": 10,
              "content": "# Staff Join\nGreeting team, it is now time for you to begin joining our campus in preparation for the session to begin. A reminder to equip your lanyard, radio and hivis jacket if required. If you have claimed a classroom, please setup that classroom as you desire. \n\nFailure to attend when you have claimed a classroom or duties will result in an immediate strike from the Human Resources Department."
            }
          ],
          "accessory": {
            "type": 2,
            "style": 5,
            "label": "Join!",
            "url": "https://www.roblox.com/games/83329354034194/Thornvale",
          }
        }
      ]
    }
  ]
}
  

    url = f"https://discord.com/api/v10/channels/{channel.id}/messages"
    headers = {
        "Authorization": f"Bot {os.environ['DISCORD_TOKEN']}",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            text = await resp.text()
            if resp.status in (200, 201):
                await interaction.followup.send(f"✅ Container sent to {channel.mention}")
            else:
                await interaction.followup.send(f"❌ Failed to send container: {resp.status} {text}")


# ---------------------------
# Run FastAPI
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
