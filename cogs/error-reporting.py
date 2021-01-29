import sys
import traceback
from io import StringIO

from discord import File
from discord.ext import commands


class ErrorReportingCog(commands.Cog):
    delete_delay = 7
    discord_character_limit = 2000

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.dioguild = self.bot.get_guild(255990138289651713)
        self.diochannel = self.dioguild.get_channel(610482665573056512)
        # self.diony = self.dioguild.get_member(81316514216554496).mention
        self.diony = (await self.dioguild.query_members(user_ids=[81316514216554496]))[0].mention

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        e_class = error.__class__
        if e_class in [commands.CommandNotFound,
                       commands.CheckFailure]:
            pass
        elif e_class == commands.CommandOnCooldown:
            await ctx.message.delete()
            await ctx.send(f'{ctx.author.mention} That command is on cooldown. Try again in {error.retry_after:.2f}s', delete_after=self.delete_delay)
        elif e_class == commands.BadArgument:
            await ctx.message.delete()
            await ctx.send(f'{ctx.author.mention} There was something wrong with your command arguments', delete_after=self.delete_delay)
        elif e_class == commands.MissingRequiredArgument:
            await ctx.message.delete()
            await ctx.send(f'{ctx.author.mention} You\'re missing at least one argument', delete_after=self.delete_delay)
        else:
            await self.context_report(ctx, error)

    async def on_error(self, event, *args, **kwargs):
        if event == 'on_message':
            ctx = await self.bot.get_context(args[0])
            await self.context_report(ctx)
        else:
            await self.general_report(event)

    async def context_report(self, ctx, error=None):
        output = (f'{self.diony}\n\n{ctx.author.display_name} said `{ctx.message.content}` '
                  f'in `#{ctx.channel}` of `{ctx.guild.name}` which caused:``````')
        await self.add_traceback(output, error)

    async def general_report(self, event):
        output = f'{self.diony}\n\nThere was an error while processing a(n) `{event}` event:``````'
        await self.add_traceback(output)

    async def add_traceback(self, preamble, error=None):
        """Replaces empty code blocks with a code block containing the current traceback.
        If the full traceback does not fit within discord's per-message character limit,
        the full traceback is included as a file attached to the message."""
        if error is not None:
            tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        else:
            tb = "".join(traceback.format_exception(*sys.exc_info()))

        # Add the first x characters of the traceback to the output up to the 2000 discord character limit
        output = preamble.replace('``````', f'```{tb[:self.discord_character_limit-len(preamble)]}```')
        # If the traceback was cut off in the line above, include the full traceback as a file
        if len(tb)+len(preamble) > self.discord_character_limit:
            await self.diochannel.send(output, file=File(fp=StringIO(tb), filename='fulltraceback.txt'))
        else:
            await self.diochannel.send(output)


def setup(bot):
    bot.add_cog(ErrorReportingCog(bot))
