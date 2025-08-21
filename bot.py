import os
import discord
from discord.ext import commands
from docx import Document
from docxtpl import DocxTemplate
import json
import re
from docx2pdf import convert

# Create folders if they don't exist
os.makedirs("templates", exist_ok=True)
os.makedirs("generated", exist_ok=True)

# Load or create template database
if not os.path.exists("templates.json"):
    with open("templates.json", "w") as f:
        json.dump({}, f)

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# Helper functions
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

# Commands
@bot.command()
async def add_template(ctx):
    await ctx.send("Please upload the DOCX template:")

    def check(msg):
        return msg.author == ctx.author and msg.attachments

    msg = await bot.wait_for("message", check=check)
    file = msg.attachments[0]
    await ctx.send("What should the template name be?")
    name_msg = await bot.wait_for("message", check=lambda m: m.author == ctx.author)
    template_name = name_msg.content

    file_path = f"templates/{file.filename}"
    await file.save(file_path)

    fields = extract_fields(file_path)
    save_template(template_name, file_path, fields)

    await ctx.send(f"Template '{template_name}' added with fields: {fields}")

@bot.command()
async def generate_document(ctx, template_name):
    with open("templates.json", "r") as f:
        templates = json.load(f)
    
    if template_name not in templates:
        await ctx.send("Template not found.")
        return
    
    fields = templates[template_name]["fields"]
    await ctx.author.send(f"Please provide the following fields: {fields}")
    
    responses = {}
    for field in fields:
        await ctx.author.send(f"Enter value for {field}:")
        def check(m):
            return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)
        msg = await bot.wait_for("message", check=check)
        responses[field] = msg.content

    # Generate DOCX
    doc = DocxTemplate(templates[template_name]["file_path"])
    doc.render(responses)
    output_path = f"generated/{ctx.author.id}_{template_name}.docx"
    doc.save(output_path)

    # Convert to PDF
    pdf_path = output_path.replace(".docx", ".pdf")
    convert(output_path, pdf_path)

    await ctx.author.send("Here is your completed document:", file=discord.File(pdf_path))

# Run bot
bot.run(os.environ['DISCORD_TOKEN'])
