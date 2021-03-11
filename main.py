import discord
from discord.ext import commands
import resources
from settings import botToken

initial_extensions = ['cogs.' + name for name in [
    'owner',
    'match-result-posting',
    'error-reporting',
    'twitch-pickem',
    'tourney-registering'
]]

if __name__ == '__main__':
    resources.init()
    bot = commands.Bot(command_prefix='!')
    for extension in initial_extensions:
        bot.load_extension(extension)
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

    bot.run(botToken)
