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

# ---------------------------
# Bot Setup
# ---------------------------
intents = discord.Intents.default()
intents.message_content = True

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

# ---------------------------
# Slash Commands
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
    await interaction.response.send_message(
        f"Generating document for template '{template_name}'. Check your DMs!", ephemeral=True
    )

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
        await interaction.followup.send(
            "Cannot DM you. Please check privacy settings.", ephemeral=True
        )
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

    # Generate DOCX
    doc = DocxTemplate(templates[template_name]["file_path"])
    doc.render(responses)
    output_docx = f"generated/{interaction.user.id}_{template_name}.docx"
    doc.save(output_docx)

    # Make viewable link via Office Online
    view_url = f"https://view.officeapps.live.com/op/embed.aspx?src={BASE_URL}/generated/{os.path.basename(output_docx)}"
    await dm_channel.send(f"Here is your document (viewable in browser): {view_url}")

# ---------------------------
# FastAPI App
# ---------------------------
app = FastAPI()
app.mount("/generated", StaticFiles(directory="generated"), name="generated")

# Railway will give you a public URL like https://your-app-name.up.railway.app
BASE_URL = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "http://localhost:8000")

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

# ---------------------------
# Run both Bot + FastAPI
# ---------------------------
threading.Thread(target=run_api, daemon=True).start()
bot.run(os.environ['DISCORD_TOKEN'])
