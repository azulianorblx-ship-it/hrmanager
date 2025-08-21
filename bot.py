import os
import discord
from discord.ext import commands
from discord import app_commands
from docxtpl import DocxTemplate
from docx import Document
import json
import re
import threading
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

# ---------------------------
# Setup folders and templates
# ---------------------------
os.makedirs("templates", exist_ok=True)
os.makedirs("generated", exist_ok=True)

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
    await bot.change_presence(activity=discord.Game(name="HR Manager Active"))

# ---------------------------
# DOCX Commands
# ---------------------------
@bot.tree.command(name="add_template", description="Add a new DOCX template")
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

@bot.tree.command(name="generate_document", description="Generate a document from a template")
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
    for field in fields:
        await dm_channel.send(f"Enter value for {field}:")
        def check(m):
            return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)
        try:
            msg = await bot.wait_for("message", check=check, timeout=300)
            responses[field] = msg.content
        except:
            await dm_channel.send("Timeout or error waiting for input.")
            return
    doc = DocxTemplate(templates[template_name]["file_path"])
    doc.render(responses)
    output_docx = f"generated/{interaction.user.id}_{template_name}.docx"
    doc.save(output_docx)
    view_url = f"https://view.officeapps.live.com/op/embed.aspx?src={BASE_URL}/generated/{os.path.basename(output_docx)}"
    await dm_channel.send(f"Here is your document (viewable in browser): {view_url}")

# ---------------------------
# DM Template Commands
# ---------------------------
@bot.tree.command(name="create_dm_template", description="Create a new DM template")
async def create_dm_template(interaction: discord.Interaction):
    await interaction.response.send_message("Send the template message in DM to the bot.")
    dm = await interaction.user.create_dm()
    try:
        msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and isinstance(m.channel, discord.DMChannel), timeout=300)
    except:
        await dm.send("Timeout. Template creation cancelled.")
        return
    content = msg.content
    fields = re.findall(r"\{\{(.*?)\}\}", content)
    await dm.send("What should the template name be?")
    try:
        name_msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user, timeout=60)
    except:
        await dm.send("Timeout. Template creation cancelled.")
        return
    template_name = name_msg.content
    save_dm_template(template_name, content, fields)
    await dm.send(f"DM template '{template_name}' saved with fields: {fields}")

@bot.tree.command(name="dm", description="Send a DM to a user, optionally using a template")
@app_commands.describe(user="User to DM", template_name="Optional template name")
async def dm_user(interaction: discord.Interaction, user: discord.User, template_name: str = None):
    dm_channel = await user.create_dm()
    responses = {}
    content_to_send = ""
    if template_name:
        with open("dm_templates.json", "r") as f:
            templates = json.load(f)
        if template_name not in templates:
            await interaction.response.send_message("Template not found.", ephemeral=True)
            return
        template = templates[template_name]
        fields = template["fields"]
        for field in fields:
            await interaction.response.send_message(f"Please provide value for {field}", ephemeral=True)
            try:
                msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel, timeout=300)
                responses[field] = msg.content
            except:
                await interaction.response.send_message("Timeout. DM cancelled.", ephemeral=True)
                return
        content_to_send = template["content"]
        for k, v in responses.items():
            content_to_send = content_to_send.replace(f"{{{{{k}}}}}", v)
    else:
        await interaction.response.send_message("Enter the message content to send:", ephemeral=True)
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel, timeout=300)
            content_to_send = msg.content
        except:
            await interaction.response.send_message("Timeout. DM cancelled.", ephemeral=True)
            return
    await dm_channel.send(content_to_send)
    await interaction.response.send_message(f"Message sent to {user.mention}.", ephemeral=True)

# ---------------------------
# List Commands
# ---------------------------
@bot.tree.command(name="list_dm_templates", description="List all DM templates")
async def list_dm_templates(interaction: discord.Interaction):
    with open("dm_templates.json", "r") as f:
        templates = json.load(f)
    if not templates:
        await interaction.response.send_message("No DM templates found.", ephemeral=True)
        return
    template_list = "\n".join(f"- {name}" for name in templates.keys())
    await interaction.response.send_message(f"**DM Templates:**\n{template_list}", ephemeral=True)

@bot.tree.command(name="list_generated_templates", description="List all DOCX templates")
async def list_generated_templates(interaction: discord.Interaction):
    with open("templates.json", "r") as f:
        templates = json.load(f)
    if not templates:
        await interaction.response.send_message("No DOCX templates found.", ephemeral=True)
        return
    template_list = "\n".join(f"- {name}" for name in templates.keys())
    await interaction.response.send_message(f"**DOCX Templates:**\n{template_list}", ephemeral=True)

# ---------------------------
# FastAPI App
# ---------------------------
app = FastAPI()
app.mount("/generated", StaticFiles(directory="generated"), name="generated")
BASE_URL = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "http://localhost:8000")

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

# ---------------------------
# Run Bot + FastAPI
# ---------------------------
threading.Thread(target=run_api, daemon=True).start()
bot.run(os.environ['DISCORD_TOKEN'])
