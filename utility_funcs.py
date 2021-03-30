import asyncio
import re

from discord.ext import commands


async def res_cog(bot):
    cog_name = 'ResourcesCog'

    if cog := bot.get_cog(cog_name):
        return cog
    raise commands.ExtensionNotFound(cog_name)


def is_channel(*args: str):
    async def predicate(ctx):
        return ctx.message.channel.name in args
    return commands.check(predicate)


def url_to_id(url: str) -> int:
    osu_mp_url = re.compile(r'((https://osu.ppy.sh/community/matches/)|(https://osu.ppy.sh/mp/))(?P<id>[0-9]+)')
    match = re.search(osu_mp_url, url)
    if match:
        return int(match.group('id'))
    else:
        raise SyntaxError("\"{}\" is not a valid mp link".format(url))


async def request(url: str, bot, headers: dict = {}) -> dict:
    '''Quick and dirty short-hand REST API grabber.'''
    session = await (await res_cog(bot)).session()
    async with session.get(url, headers=headers) as r:
        if r.status != 200:
            raise Exception('External server returned status code other than 200')
        json = await r.json()
    return json


async def confirm(prompt, ctx, timeout=20.0):
    message = await ctx.send(prompt)
    await message.add_reaction('✅')
    await message.add_reaction('❌')

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ['✅', '❌']

    try:
        reaction, user = await ctx.bot.wait_for('reaction_add', timeout=timeout, check=check)
    except asyncio.TimeoutError:
        await message.delete()
        return False
    else:
        await message.delete()
        return str(reaction.emoji) == '✅'
