import discord
from discord.ext import commands
from discord.app_commands import MissingPermissions

from utility_funcs import res_cog


class AmplifierDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Amplifier Option One', description='First amplifier option provided above', emoji='1️⃣'),
            discord.SelectOption(label='Amplifier Option Two', description='Second amplifier option provided above', emoji='2️⃣'),
            discord.SelectOption(label='Amplifier Option Three', description='Third amplifier option provided above', emoji='3️⃣'),
            discord.SelectOption(label='Lucky Dip', description='Give me a random amplifier not listed above', emoji='🎲'),
        ]
        super().__init__(placeholder='Pick one amplifier...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # TODO: persist user's choice (self.values[0]) in database and spit back to the user
        await interaction.response.send_message(f"You've picked the amplifier \"TODO\"")


class AmplifierDropdownView(discord.ui.View):
    # TODO: Make this view persisitent as per (https://github.com/Rapptz/discord.py/blob/master/examples/views/persistent.py)
    def __init__(self):
        super().__init__()
        self.add_item(AmplifierDropdown())


class AmplifiersCog(commands.Cog):
    def __init__(self, bot):
        self.players = [153711384712970240, 81316514216554496]
        self.bot = bot

        self.discord_numbers = {
            1: "one",
            2: "two",
            3: "three",
            4: "four",
            5: "five",
            6: "six",
            7: "seven",
            8: "eight",
            9: "nine"
        }

    async def _connpool(self):
        return await res_cog(self.bot).connpool()

    @discord.app_commands.command()
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def trigger(self, interaction: discord.Interaction):
        # TODO: automate the retreival and sending of messages to players
        await interaction.response.defer(thinking=True, ephemeral=True)
        for player in self.players:
            await self.send_amplifier_options(player)
        await interaction.followup.send('done', ephemeral=True)

    @trigger.error
    async def trigger_error(self, interaction, error):
        if isinstance(error, MissingPermissions):
            await interaction.response.send_message('You don\'t have permission to use that command.', ephemeral=True)
        else:
            raise error

    async def send_amplifier_options(self, discord_id):
        view = AmplifierDropdownView()
        member = self.bot.get_user(discord_id)

        async with (await self._connpool()).acquire() as conn:
            options = await conn.fetch('''
                select amplifier_name from amplifier_picks
                    natural left join players
                    natural left join amplifiers
                    where discord_id=$1
                    order by amplifier_id asc;''', member.id)

        preamble = f'Your options for amplifiers this week are:\n\n'
        for i, option in enumerate(options):
            preamble += f':{self.discord_numbers[i+1]}: - "{option["amplifier_name"]}"\n'
        preamble += "\nYou have until Wednesday at 5pm to pick one of the below or one of the amplifiers will be selected at random (not lucky dip)."
        await member.send(preamble, view=view)


async def setup(bot):
    await bot.add_cog(AmplifiersCog(bot))
