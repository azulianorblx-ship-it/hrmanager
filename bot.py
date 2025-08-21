# ---------------------------
# Slash Commands
# ---------------------------
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

    # Send DOCX directly
    await dm_channel.send("Here is your completed document:", file=discord.File(output_path))
    print("Sent DOCX to user DM successfully")
