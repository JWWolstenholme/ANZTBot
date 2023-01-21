import asyncio

import discord
from discord.ext import commands

from utility_funcs import get_setting

initial_extensions = ['cogs.' + name for name in [
    'owner',
    'error-reporting',
    'resources',
    'tourney-signup',
    'twitch-pickem',
    'match-result-posting',
    'qualifiers'
]]


async def main():
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    bot = commands.Bot(command_prefix='!', intents=intents)
    for extension in initial_extensions:
        await bot.load_extension(extension)
        print(f'Loaded \'{extension}\'')

    @bot.event
    async def on_ready():
        print(f'Logged in as: {bot.user.name} - {bot.user.id}\nVersion: {discord.__version__}')

    @bot.event
    async def on_error(event, *args, **kwargs):
        """Handle these types of errors in the error-handling cog if the cog is loaded."""
        try:
            cog = bot.cogs['ErrorReportingCog']
            await cog.on_error(event, *args, **kwargs)
        except KeyError:
            return

    async with bot:
        await bot.start(get_setting("discord.py", "bot_token"))

if __name__ == '__main__':
    asyncio.run(main())
