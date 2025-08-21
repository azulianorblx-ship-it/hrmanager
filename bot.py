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
        await self.tree.sync(guild=discord.Object(id=int(os.environ['GUILD_ID'])))  # sync to your guild for instant registration
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
    BASE_URL = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "http://localhost:8000")
    view_url = f"https://view.officeapps.live.com/op/embed.aspx?src={BASE_URL}/generated/{os.path.basename(output_docx)}"
    await dm_channel.send(f"Here is your document (viewable in browser): {view_url}")

# ---------------------------
# FastAPI App
# ---------------------------
app = FastAPI()
app.mount("/generated", StaticFiles(directory="generated"), name="generated")

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

# ---------------------------
# Vacancy/HR Commands
# ---------------------------
vacancy_tickets = {}  # {ticket_message_id: {"user_id": ..., "channel_id": ...}}

RECRUITMENT_ROLE_ID = 1407614964214267934
CAREERS_CHANNEL_ID = 1405613279648153743

from discord.ui import Button, View

@bot.tree.command(name="new_vacancy", description="Post a new job vacancy")
@app_commands.guilds(discord.Object(id=int(os.environ['GUILD_ID'])))
async def new_vacancy(interaction: discord.Interaction):
    if RECRUITMENT_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("You do not have permission.", ephemeral=True)
        return

    await interaction.response.send_message("Please check your DMs to fill vacancy details.", ephemeral=True)
    dm_channel = await interaction.user.create_dm()

    responses = {}
    fields = ["vacancy_name", "job_description", "manager", "requirements"]
    def check(m): return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

    for field in fields:
        await dm_channel.send(f"Enter {field.replace('_',' ').title()}:")
        try:
            msg = await bot.wait_for("message", check=check, timeout=300)
            responses[field] = msg.content
        except:
            await dm_channel.send("Timeout. Vacancy creation cancelled.")
            return

    careers_channel = bot.get_channel(CAREERS_CHANNEL_ID)
    if not careers_channel:
        await dm_channel.send("Careers channel not found.")
        return

    # Create Apply button
    button = Button(label="Apply", style=discord.ButtonStyle.primary)
    async def button_callback(interaction_button: discord.Interaction):
        applicant = interaction_button.user
        ticket_dm = await applicant.create_dm()
        await ticket_dm.send("Hello! Please send your CV (PDF, DOCX, or viewable link).")
        vacancy_tickets[ticket_dm.id] = {"user_id": applicant.id, "channel_id": ticket_dm.id}
        await interaction_button.response.send_message("HR will review your CV.", ephemeral=True)
    button.callback = button_callback
    view = View()
    view.add_item(button)

    embed = discord.Embed(title=responses["vacancy_name"], description=responses["job_description"], color=0x00ff00)
    embed.add_field(name="Manager", value=responses["manager"], inline=True)
    embed.add_field(name="Requirements", value=responses["requirements"], inline=False)
    await careers_channel.send(embed=embed, view=view)
    await dm_channel.send(f"Vacancy posted successfully in {careers_channel.mention}.")

@bot.tree.command(name="close", description="Close a vacancy ticket")
@app_commands.describe(ticket_id="Ticket message ID to close")
async def close_ticket(interaction: discord.Interaction, ticket_id: str):
    if RECRUITMENT_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("You do not have permission.", ephemeral=True)
        return

    ticket_id_int = int(ticket_id)
    if ticket_id_int not in vacancy_tickets:
        await interaction.response.send_message("Ticket not found.", ephemeral=True)
        return

    user_id = vacancy_tickets[ticket_id_int]["user_id"]
    user = await bot.fetch_user(user_id)
    if user:
        dm_channel = await user.create_dm()
        await dm_channel.send("Your HR ticket has been closed.")
    del vacancy_tickets[ticket_id_int]
    await interaction.response.send_message("Ticket closed successfully.", ephemeral=True)

# ---------------------------
# Run both Bot + FastAPI
# ---------------------------
threading.Thread(target=run_api, daemon=True).start()
bot.run(os.environ['DISCORD_TOKEN'])
