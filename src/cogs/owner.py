from discord import Embed
from discord.ext import commands
from discord.ext.commands import MemberConverter, MemberNotFound

from utility_funcs import _get_settings, set_exposed_setting


class OwnerCog(commands.Cog, command_attrs=dict(hidden=True)):
    delete_delay = 10

    def __init__(self, bot):
        self.bot = bot

    async def error(self, ctx, e):
        await ctx.send(f'Error: {type(e).__name__} - {e}', delete_after=self.delete_delay)

    async def success(self, ctx):
        await ctx.send('Success', delete_after=self.delete_delay)

    async def cog_before_invoke(self, ctx):
        if ctx.guild is not None:
            await ctx.message.delete()

    @commands.Cog.listener()
    async def on_message(self, message):
        '''Forward all private messages to Diony'''
        diony = self.bot.get_user(81316514216554496)
        author = message.author

        if (author == self.bot.user or          # Bot message
            author == diony or                  # Diony message
            message.guild is not None):         # Not a DM
            return

        files = [await attachment.to_file(spoiler=attachment.is_spoiler()) for attachment in message.attachments]
        await diony.send(f'{author.global_name} ({author.id}) said:\n{message.content}', files=files)

    @commands.command()
    @commands.is_owner()
    async def dm(self, ctx, member, *, the_rest):
        # Consider making converter greedy see (https://discordpy.readthedocs.io/en/stable/ext/commands/commands.html?highlight=converter#greedy) for reference.
        try:
            member = await MemberConverter().convert(ctx, member)
        except MemberNotFound:
            await ctx.send("Couldn't find a user with what you provided.", delete_after=self.delete_delay)
            return

        await member.send(the_rest)

    @commands.command()
    @commands.is_owner()
    async def say(self, ctx, *, the_rest=""):
        if not the_rest.strip():
            return
        await ctx.send(the_rest)

    @commands.command()
    @commands.is_owner()
    async def cogs(self, ctx):
        cogs = '\n'.join(self.bot.extensions.keys())
        await ctx.send(f'Loaded extensions:```\n{cogs}```', delete_after=self.delete_delay)

    @commands.command()
    @commands.is_owner()
    async def load(self, ctx, *, cog: str):
        try:
            await self.bot.load_extension(cog)
        except Exception as e:
            await self.error(ctx, e)
        else:
            await self.success(ctx)

    @commands.command()
    @commands.is_owner()
    async def unload(self, ctx, *, cog: str):
        try:
            await self.bot.unload_extension(cog)
        except Exception as e:
            await self.error(ctx, e)
        else:
            await self.success(ctx)

    @commands.command()
    @commands.is_owner()
    async def reload(self, ctx, *, cog: str):
        try:
            await self.bot.reload_extension(cog)
        except Exception as e:
            await self.error(ctx, e)
        else:
            await self.success(ctx)

    @commands.command()
    @commands.is_owner()
    async def logout(self, ctx):
        await self.bot.close()

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def purge(self, ctx, limit: int):
        await ctx.channel.purge(limit=limit)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def settings(self, ctx):
        data = _get_settings()

        description = ''
        for category in data:
            if 'exposed_settings' in data[category]:
                description += f'**{category}**\n```'
                for setting in data[category]['exposed_settings']:
                    description += f'{setting} = {data[category]["exposed_settings"][setting]}\n'
                description += '```'

        embed = Embed(title='Settings', description=description, color=0xe47607)
        embed.set_footer(text=f'Replying to {ctx.author.display_name}')
        await ctx.send(embed=embed)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def set(self, ctx, category, setting, value):
        try:
            if set_exposed_setting(category, setting, value):
                await ctx.send(f'{ctx.author.mention} Done', delete_after=self.delete_delay)
            else:
                await ctx.send(f'{ctx.author.mention} That setting couldn\'t be set. It might not exist.', delete_after=self.delete_delay)
        except Exception:
            await ctx.send(f'{ctx.author.mention} There was an error setting that setting.', delete_after=self.delete_delay)


async def setup(bot):
    await bot.add_cog(OwnerCog(bot))
