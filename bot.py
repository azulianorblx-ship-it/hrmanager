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
# ---------------------------import os
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
GUILD_ID = int(os.environ.get("GUILD_ID"))
LOG_CHANNEL_ID = 1408784982205534239

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
        await channel.send(f"📘 **Log:** {message}")

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
    file_path = f"templates/{file.filename}"
    await file.save(file_path)
    fields = extract_fields(file_path)
    save_template(template_name, file_path, fields)
    await interaction.followup.send(f"Template '{template_name}' added with fields: {fields}")
    await log_action(bot, f"{interaction.user} added template '{template_name}'")

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
    await interaction.response.send_message(f"DM Templates:\n" + "\n".join(templates.keys()), ephemeral=True)
    await log_action(bot, f"{interaction.user} listed DM templates")

@bot.tree.command(name="list_generated_templates", description="List all generated DOCX templates", guild=discord.Object(id=GUILD_ID))
async def list_generated_templates(interaction: discord.Interaction):
    with open("templates.json", "r") as f:
        templates = json.load(f)
    if not templates:
        await interaction.response.send_message("No DOCX templates found.", ephemeral=True)
        return
    await interaction.response.send_message(f"DOCX Templates:\n" + "\n".join(templates.keys()), ephemeral=True)
    await log_action(bot, f"{interaction.user} listed DOCX templates")

@bot.tree.command(name="dm", description="Send a DM to a user, optionally using a template", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="Target user", template="Template name (optional)")
async def dm_user(interaction: discord.Interaction, user: discord.User, template: str = None):
    dm_channel = await user.create_dm()
    def check(m):
        return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

    if template:
        with open("dm_templates.json", "r") as f:
            templates = json.load(f)
        if template not in templates:
            await interaction.response.send_message("Template not found.", ephemeral=True)
            return
        fields = templates[template]["fields"]
        content = templates[template]["content"]
        responses = {}
        try:
            await interaction.response.send_message(f"Filling template '{template}'. Check DMs.", ephemeral=True)
            for field in fields:
                await interaction.user.send(f"Enter value for {field}:")
                msg = await bot.wait_for("message", check=check, timeout=300)
                responses[field] = msg.content
            final_message = content
            for k, v in responses.items():
                final_message = final_message.replace(f"{{{{{k}}}}}", v)
            await dm_channel.send(final_message)
            await log_action(bot, f"{interaction.user} sent DM to {user} using template '{template}'")
        except asyncio.TimeoutError:
            await interaction.user.send("Timeout filling template. DM cancelled.")
    else:
        await interaction.response.send_message("Please check your DMs to type your message.", ephemeral=True)
        try:
            await interaction.user.send("Enter your DM message to send:")
            msg = await bot.wait_for("message", check=check, timeout=600)
            await dm_channel.send(msg.content)
            await log_action(bot, f"{interaction.user} sent DM to {user}")
        except asyncio.TimeoutError:
            await interaction.user.send("Timeout. DM cancelled.")

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
# Slash Commands
# ---------------------------
@bot.tree.command(name="create_embedtemplate", description="Create a new embed template")
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
        await dm_channel.send(prompt)
        try:
            msg = await bot.wait_for("message", check=check, timeout=600)
            responses[key] = msg.content
        except asyncio.TimeoutError:
            await dm_channel.send("Timeout. Template creation cancelled.")
            return

    # Parse color
    color = discord.Color.dark_blue()
    if responses.get("color"):
        try:
            color = discord.Color(int(responses["color"].replace("#", ""), 16))
        except:
            pass

    data = {
        "title": responses["title"],
        "description": responses["description"],
        "footer": responses.get("footer", ""),
        "color": color.value,
        "image_url": responses.get("image_url", ""),
        "thumbnail_url": responses.get("thumbnail_url", ""),
        "channel_id": int(responses["channel_id"]),
        "ping": responses.get("ping", "none")
    }

    save_embed_template(responses["name"], data)
    await dm_channel.send(f"✅ Embed template '{responses['name']}' saved!")
    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"📦 {interaction.user} created embed template '{responses['name']}'.")

@bot.tree.command(name="list_embedtemplates", description="List all saved embed templates")
async def list_embedtemplates(interaction: discord.Interaction):
    templates = load_embed_templates()
    if not templates:
        await interaction.response.send_message("No embed templates found.", ephemeral=True)
        return
    await interaction.response.send_message("📑 Embed Templates:\n" + "\n".join(templates.keys()), ephemeral=True)

@bot.tree.command(name="embed", description="Send a custom or template embed")
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

    # Template mode
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

    # Parse color if hex provided
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
    embed = Embed(
        title=title or "Untitled",
        description=description or "",
        color=color,
        timestamp=datetime.utcnow()
    )
    if footer: embed.set_footer(text=footer)
    if image_url: embed.set_image(url=image_url)
    if thumbnail_url: embed.set_thumbnail(url=thumbnail_url)

    # Send
    if not channel:
        await interaction.followup.send("❌ No channel specified.", ephemeral=True)
        return

    mention = ping if ping.lower() != "none" else ""
    await channel.send(content=mention, embed=embed)

    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"📢 {interaction.user} sent an embed in {channel.mention} (template: {template or 'custom'})")

# ---------------------------
# Announcement Template Commands
# ---------------------------
@bot.tree.command(name="update_anntemplate", description="Update the announcement DOCX template", guild=discord.Object(id=GUILD_ID))
async def update_anntemplate(interaction: discord.Interaction):
    await interaction.response.send_message("Upload your new announcement DOCX template as a reply in this channel.", ephemeral=True)

    def check(msg):
        return msg.author == interaction.user and msg.attachments and msg.channel == interaction.channel

    try:
        msg = await bot.wait_for("message", check=check, timeout=120)
    except asyncio.TimeoutError:
        await interaction.followup.send("Timeout waiting for file.", ephemeral=True)
        return

    file = msg.attachments[0]
    file_path = f"templates/{file.filename}"
    await file.save(file_path)
    fields = extract_fields(file_path)
    save_template("announcement", file_path, fields)
    await interaction.followup.send(f"Announcement template updated with fields: {fields}", ephemeral=True)
    await log_action(bot, f"{interaction.user} updated announcement template")

@bot.tree.command(name="announcement", description="Send an announcement using the template", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(channel="Announcement channel to post in")
async def announcement(interaction: discord.Interaction, channel: discord.TextChannel):
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
        def dm_check(m):
            return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

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
        color=discord.Color.dark_blue(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=f"Sent by {full_name}")

    preview = await dm_channel.send("Here is a preview of your announcement:", embed=embed)
    await dm_channel.send("Reply with 'accept' to post or 'deny' to cancel.")

    def confirm_check(m):
        return m.author == interaction.user and isinstance(m.channel, discord.DMChannel) and m.content.lower() in ["accept", "deny"]

    try:
        confirm_msg = await bot.wait_for("message", check=confirm_check, timeout=300)
    except asyncio.TimeoutError:
        await dm_channel.send("Timeout. Announcement cancelled.")
        return

    if confirm_msg.content.lower() == "deny":
        await dm_channel.send("Announcement cancelled.")
        await log_action(bot, f"{interaction.user} cancelled announcement")
        return

    await channel.send(content="@everyone", embed=embed)
    await interaction.followup.send(f"Announcement sent in {channel.mention}", ephemeral=True)
    await log_action(bot, f"{interaction.user} posted announcement in {channel}")

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
