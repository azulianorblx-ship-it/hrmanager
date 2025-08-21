import os
import discord
from discord.ext import commands
from discord import app_commands
from docx import Document
from docxtpl import DocxTemplate
import json
import re
import subprocess
import platform

# ---------------------------
# Setup folders and templates
# ---------------------------
os.makedirs("templates", exist_ok=True)
os.makedirs("generated", exist_ok=True)

if not os.path.exists("templates.json"):
    with open("templates.json", "w") as f:
        json.dump({}, f)
    print("Created templates.json file")

# ---------------------------
# Helper functions
# ---------------------------
def extract_fields(file_path):
    print(f"Extracting fields from {file_path}")
    doc = Document(file_path)
    text = "\n".join([p.text for p in doc.paragraphs])
    fields = re.findall(r"\{\{(.*?)\}\}", text)
    fields_set = list(set(fields))
    print(f"Found fields: {fields_set}")
    return fields_set

def save_template(template_name, file_path, fields):
    print(f"Saving template {template_name}")
    with open("templates.json", "r") as f:
        templates = json.load(f)
    templates[template_name] = {"file_path": file_path, "fields": fields}
    with open("templates.json", "w") as f:
        json.dump(templates, f, indent=4)
    print(f"Template {template_name} saved successfully")

def convert_to_pdf(input_path, output_path):
    system = platform.system()
    print(f"Converting to PDF on {system}")
    try:
        if system == "Windows" or system == "Darwin":
            # Use docx2pdf on Windows/macOS
            from docx2pdf import convert
            convert(input_path, output_path)
        else:
            # Use LibreOffice CLI on Linux
            subprocess.run([
                "libreoffice",
                "--headless",
                "--convert-to", "pdf",
                "--outdir", os.path.dirname(output_path),
                input_path
            ], check=True)
        print(f"PDF conversion successful: {output_path}")
        return True
    except Exception as e:
        print(f"Error converting to PDF: {e}")
        return False

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
    await interaction.response.send_message("Please upload your DOCX template as a reply in this channel.")
    print(f"/add_template called by {interaction.user}")

    def check(msg):
        return msg.author == interaction.user and msg.attachments and msg.channel == interaction.channel

    try:
        msg = await bot.wait_for("message", check=check, timeout=120)
    except Exception as e:
        await interaction.followup.send("Timeout or error waiting for file.")
        print(f"Error waiting for file: {e}")
        return

    file = msg.attachments[0]
    await interaction.followup.send("What should the template name be?")
    
    try:
        name_msg = await bot.wait_for(
            "message",
            check=lambda m: m.author == interaction.user and m.channel == interaction.channel,
            timeout=60
        )
    except Exception as e:
        await interaction.followup.send("Timeout or error waiting for template name.")
        print(f"Error waiting for template name: {e}")
        return

    template_name = name_msg.content
    file_path = f"templates/{file.filename}"
    await file.save(file_path)
    print(f"Saved template file to {file_path}")

    fields = extract_fields(file_path)
    save_template(template_name, file_path, fields)

    await interaction.followup.send(f"Template '{template_name}' added with fields: {fields}")

@bot.tree.command(name="generate_document", description="Generate a document from a template")
@app_commands.describe(template_name="Name of the template to use")
async def generate_document(interaction: discord.Interaction, template_name: str):
    print(f"/generate_document called by {interaction.user} for template {template_name}")
    await interaction.response.send_message(
        f"Generating document for template '{template_name}'. Check your DMs!", ephemeral=True
    )

    with open("templates.json", "r") as f:
        templates = json.load(f)

    if template_name not in templates:
        await interaction.followup.send("Template not found.", ephemeral=True)
        print("Template not found in templates.json")
        return

    fields = templates[template_name]["fields"]
    print(f"Template fields: {fields}")

    try:
        dm_channel = await interaction.user.create_dm()
        await dm_channel.send(f"Please provide the following fields: {fields}")
    except Exception as e:
        print(f"Error creating DM: {e}")
        await interaction.followup.send(
            "Cannot send you a DM. Please check your privacy settings.", ephemeral=True
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
        except Exception as e:
            await dm_channel.send("Timeout or error waiting for input.")
            print(f"Error waiting for input for {field}: {e}")
            return

    # Generate DOCX
    doc = DocxTemplate(templates[template_name]["file_path"])
    doc.render(responses)
    output_path = f"generated/{interaction.user.id}_{template_name}.docx"
    doc.save(output_path)
    print(f"Generated DOCX at {output_path}")

    # Convert to PDF
    pdf_path = output_path.replace(".docx", ".pdf")
    if not convert_to_pdf(output_path, pdf_path):
        await dm_channel.send("Error converting document to PDF. PDF not generated.")
        return

    await dm_channel.send("Here is your completed document:", file=discord.File(pdf_path))
    print("Sent PDF to user DM successfully")

# ---------------------------
# Run Bot
# ---------------------------
bot.run(os.environ['DISCORD_TOKEN'])
