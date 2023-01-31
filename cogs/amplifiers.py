import asyncio

import discord
from discord.app_commands import MissingPermissions
from discord.ext import commands

from utility_funcs import get_setting, res_cog


class AmplifierDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Amplifier Option One', description='First amplifier option provided above', emoji='1️⃣', value=0),
            discord.SelectOption(label='Amplifier Option Two', description='Second amplifier option provided above', emoji='2️⃣', value=1),
            discord.SelectOption(label='Amplifier Option Three', description='Third amplifier option provided above', emoji='3️⃣', value=2),
            discord.SelectOption(label='Lucky Dip', description='Give me a random amplifier not listed above', emoji='🎲', value=3)
        ]
        super().__init__(placeholder='Pick one amplifier...', min_values=1, max_values=1, options=options, custom_id='amplifier-select-persistent')

    async def callback(self, interaction: discord.Interaction):
        selected_option = int(self.values[0])

        await interaction.response.defer(thinking=True)

        connpool = await res_cog(interaction.client).connpool()

        week_no = get_setting('amplifiers', 'week_number')

        async with connpool.acquire() as conn:
            async with conn.transaction():
                # Convert user's discord id to their osu! ID.
                osu_id = int(await conn.fetchval('''select osu_id from players where discord_id=$1;''', interaction.user.id))
                # Reset their current picks TODO: Make sure this doesn't mess up future weeks where there will be multiple picks
                await conn.execute('''update players_amplifiers set is_picked=False where osu_id=$1 and week=$2;''', osu_id, week_no)
                # Convert the users picked option to it's corresponding amplifier
                options = await conn.fetch('''
                    select pa.amplifier_id, amplifier_name from players_amplifiers as pa
                        natural left join players
                        left join amplifiers as a on pa.amplifier_id = a.amplifier_id
                        where discord_id=$1
                        and pa.week=$2
                        order by amplifier_id asc;''', interaction.user.id, week_no)
                selected_amplifier_record = options[selected_option]
                # Set the picked amplifiers as picked
                await conn.execute('''update players_amplifiers set is_picked=True where osu_id=$1 and amplifier_id=$2 and week=$3;''', osu_id, selected_amplifier_record['amplifier_id'], week_no)

        if selected_amplifier_record['amplifier_id'] == 777:
            await interaction.followup.send(f'You\'ve picked "{selected_amplifier_record["amplifier_name"]}". This will draw you a new amplifier not listed above once the selection period is over.')
        else:
            await interaction.followup.send(f'You\'ve picked the amplifier "{selected_amplifier_record["amplifier_name"]}"')


class AmplifierDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AmplifierDropdown())

    def on_error(self, interaction, error, item):
        # TODO: Handle these errors better. Ideally incorperate interaction errors with the error-reporting cog.
        raise error


class AmplifiersCog(commands.Cog):
    def __init__(self, bot):
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

        self.bot.add_view(AmplifierDropdownView())

    async def _connpool(self):
        return await res_cog(self.bot).connpool()

    @discord.app_commands.command()
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def request_pick(self, interaction: discord.Interaction, discord_ids: str, delay_seconds: int):
        ids = discord_ids.split('|')
        await interaction.response.defer(thinking=True, ephemeral=True)
        for i in ids:
            await self.send_amplifier_options(int(i))
            await asyncio.sleep(delay=delay_seconds)
        await interaction.followup.send('done', ephemeral=True)

    @request_pick.error
    async def request_pick_error(self, interaction, error):
        if isinstance(error, MissingPermissions):
            await interaction.response.send_message('You don\'t have permission to use that command.', ephemeral=True)
        else:
            raise error

    async def send_amplifier_options(self, discord_id):
        view = AmplifierDropdownView()
        member = self.bot.get_user(discord_id)

        week_no = get_setting('amplifiers', 'week_number')

        async with (await self._connpool()).acquire() as conn:
            options = await conn.fetch('''
                select pa.amplifier_id, amplifier_name from players_amplifiers as pa
                    natural left join players
                    left join amplifiers as a on pa.amplifier_id = a.amplifier_id
                    where discord_id=$1
                    and pa.week=$2
                    order by amplifier_id asc;''', member.id, week_no)

        preamble = f'Hello! Your options for amplifiers this week are:\n\n'
        for i, option in enumerate(options):
            emote = ":game_die:" if option['amplifier_name'] == "Lucky Dip" else f":{self.discord_numbers[i+1]}:"
            preamble += f'{emote} - "{option["amplifier_name"]}"\n'
        preamble += "\nRefer to the main sheet for amplifier descriptions (<https://bit.ly/ANZT10SAmplifierDescriptions>)\nYou have until 9pm Thursday 26th (AEDT) to pick one of the above amplifiers or one of them will be selected at random (except lucky dip).\nPlease also note, if you reschedule your match to prior to 3am Friday 27th (AEDT), your amplifiers must be locked in 6 hours prior to the match."
        try:
            await member.send(preamble, view=view)
            await self.bot_log(f"✅ Sent amplifier options to user with discord_id: {discord_id}, tag: {member.name}#{member.discriminator}")
        except discord.errors.Forbidden:
            await self.bot_log(f"❌ Failed to send amplifier options to user with discord_id: {discord_id}, tag: {member.name}#{member.discriminator}")

    async def bot_log(self, text):
        anztguild = self.bot.get_guild(199158455888642048)
        if anztguild is None:
            return
        botlogchannel = anztguild.get_channel(731069297295753318)
        await botlogchannel.send(text)


async def setup(bot):
    await bot.add_cog(AmplifiersCog(bot))
