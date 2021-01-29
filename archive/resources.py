import discord


class ResourcesCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def send_typing(self, f):
        '''Decorater that can be used to send typing indicator. Only works on
        methods that have a message or context as their first parameter.'''
        @wraps(f)
        async def wrapped(*args):
            if args[0].__class__ == discord.ext.commands.Context:
                async with args[0].typing():
                    return await f(*args)
            elif args[0].__class__ == discord.Message:
                async with args[0].channel.typing():
                    return await f(*args)
        return wrapped


def setup(bot):
    bot.add_cog(ResourcesCog(bot))
