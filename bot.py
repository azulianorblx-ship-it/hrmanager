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

    # Construct view-only link using Office Web Viewer
    file_url = f"{BASE_URL}/templates/{file.filename}"  # Pointing to templates folder
    encoded_url = urllib.parse.quote(file_url, safe="")
    view_only_link = f"https://view.officeapps.live.com/op/embed.aspx?src={encoded_url}"

    await interaction.followup.send(
        f"Template '{template_name}' added with fields: {fields}\n"
        f"View-only link for this template: {view_only_link}"
    )
