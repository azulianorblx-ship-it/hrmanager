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
GUILD_ID = int(os.environ.get("GUILD_ID", 0))
if not GUILD_ID:
    raise ValueError("GUILD_ID not set in environment variables")

LOG_CHANNEL_ID = 1408784982205534239
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
    with open("templates.json", "r") as f:
        templates = json.load(f)
    if not templates:
        await interaction.response.send_message("No DOCX templates found.", ephemeral=True)
        return
    await interaction.response.send_message("📑 DOCX Templates:\n" + "\n".join(templates.keys()), ephemeral=True)

@bot.tree.command(name="generate_document", description="Generate a document from a template", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(template_name="Name of the template to use")
async def generate_document(interaction: discord.Interaction, template_name: str):
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

# ---------------------------
# DM Template Commands
# ---------------------------
@bot.tree.command(name="create_dm_template", description="Create a new DM template", guild=discord.Object(id=GUILD_ID))
async def create_dm_template(interaction: discord.Interaction):
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
    with open("dm_templates.json", "r") as f:
        templates = json.load(f)
    if not templates:
        await interaction.response.send_message("No DM templates found.", ephemeral=True)
        return
    await interaction.response.send_message("📑 DM Templates:\n" + "\n".join(templates.keys()), ephemeral=True)

@bot.tree.command(name="send_dm", description="Send a DM to a user using a saved template", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(template_name="The DM template to use", user="User to send the DM to")
async def send_dm(interaction: discord.Interaction, template_name: str, user: discord.User):
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
# Embed Commands
# ---------------------------
@bot.tree.command(name="create_embedtemplate", description="Create a new embed template", guild=discord.Object(id=GUILD_ID))
async def create_embedtemplate(interaction: discord.Interaction):
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
    templates = load_embed_templates()
    if not templates:
        await interaction.response.send_message("No embed templates found.", ephemeral=True)
        return
    await interaction.response.send_message("📑 Embed Templates:\n" + "\n".join(templates.keys()), ephemeral=True)

@bot.tree.command(name="embed", description="Send a custom or template embed", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(
    template="Name of a saved embed template (optional)",
    title="Embed title (if not using template)",
    description="Embed description (if not using template)",
    footer="Embed footer (optional)",
    color="Embed color (hex, optional)",
    image_url="Image URL (optional)",
    thumbnail_url="Thumbnail URL (optional)",
    channel="Target channel (if not using template)",
    ping="Ping string (e.g. @everyone, @here, role mention, or none)"
)
async def embed(
    interaction: discord.Interaction,
    template: str = None,
    title: str = None,
    description: str = None,
    footer: str = None,
    color: str = None,
    image_url: str = None,
    thumbnail_url: str = None,
    channel: discord.TextChannel = None,
    ping: str = "none"
):
    await interaction.response.send_message("Processing embed...", ephemeral=True)

    if template:
        templates = load_embed_templates()
        if template not in templates:
            await interaction.followup.send("❌ Template not found.", ephemeral=True)
            return
        data = templates[template]
        title, description, footer = data["title"], data["description"], data["footer"]
        color = data["color"]
        image_url, thumbnail_url = data["image_url"], data["thumbnail_url"]
        channel = interaction.guild.get_channel(data["channel_id"])
        ping = data["ping"]
        
    # Parse color (always runs, whether template or manual args)
    if color and isinstance(color, str):
        try:
            color = discord.Color(int(color.replace("#", ""), 16))
        except:
            color = DARK_BLUE
    elif isinstance(color, int):
        color = discord.Color(color)
    else:
        color = DARK_BLUE      

    # Build embed
    embed_obj = Embed(
        title=title or "Untitled",
        description=description or "",
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    if footer:
        embed_obj.set_footer(text=footer)
    if image_url and image_url.lower().startswith(("http://", "https://")):
        embed_obj.set_image(url=image_url)
    if thumbnail_url and thumbnail_url.lower().startswith(("http://", "https://")):
        embed_obj.set_thumbnail(url=thumbnail_url)

    # Send
    if not channel:
        await interaction.followup.send("❌ No channel specified.", ephemeral=True)
        return

    mention = ping if ping.lower() != "none" else ""
    await channel.send(content=mention, embed=embed_obj)

    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"📢 {interaction.user} sent an embed in {channel.mention} "
            f"(template: {template or 'custom'})"
        )

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
