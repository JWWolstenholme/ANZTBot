from discord.ext import commands


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

    @commands.command()
    @commands.is_owner()
    async def cogs(self, ctx):
        cogs = '\n'.join(self.bot.extensions.keys())
        await ctx.send(f'Loaded extensions:```\n{cogs}```', delete_after=self.delete_delay)

    @commands.command()
    @commands.is_owner()
    async def load(self, ctx, *, cog: str):
        try:
            self.bot.load_extension(cog)
        except Exception as e:
            await self.error(ctx, e)
        else:
            await self.success(ctx)

    @commands.command()
    @commands.is_owner()
    async def unload(self, ctx, *, cog: str):
        try:
            self.bot.unload_extension(cog)
        except Exception as e:
            await self.error(ctx, e)
        else:
            await self.success(ctx)

    @commands.command()
    @commands.is_owner()
    async def reload(self, ctx, *, cog: str):
        try:
            self.bot.reload_extension(cog)
        except Exception as e:
            await self.error(ctx, e)
        else:
            await self.success(ctx)

    @commands.command()
    @commands.is_owner()
    async def logout(self, ctx):
        await self.bot.logout()


def setup(bot):
    bot.add_cog(OwnerCog(bot))
