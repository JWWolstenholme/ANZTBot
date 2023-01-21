from discord import Embed
from discord.ext import commands
from utility_funcs import _get_settings, is_channel, set_exposed_setting


class OwnerCog(commands.Cog, command_attrs=dict(hidden=True)):
    delete_delay = 10

    def __init__(self, bot):
        self.bot = bot

    async def error(self, ctx, e):
        await ctx.send(f'Error: {type(e).__name__} - {e}', delete_after=self.delete_delay)

    async def success(self, ctx):
        await ctx.send('Success', delete_after=self.delete_delay)

    async def cog_before_invoke(self, ctx):
        await ctx.message.delete()

    @commands.Cog.listener()
    async def on_message(self, message):
        '''Forward all private messages to Diony'''
        if (message.author == self.bot.user or
                message.guild is not None or
                message.author.bot):
            return

        diony = self.bot.get_user(81316514216554496)
        author = message.author
        await diony.send(f'{author.name}#{author.discriminator} (ID: `{author.id}`) said:\n{message.content}')

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
