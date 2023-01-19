import asyncio
import json
import re

from discord.ext import commands


def res_cog(bot):
    cog_name = 'ResourcesCog'

    if cog := bot.get_cog(cog_name):
        return cog
    raise commands.ExtensionNotFound(cog_name)


settings_file = 'settings.jsonc'


def _get_settings():
    with open(settings_file, 'r') as f:
        data = json.load(f)
    return data


def get_setting(category, setting=None):
    data = _get_settings()
    category = data[category]
    if not setting:
        return category

    return category['exposed_settings'][setting] if ('exposed_settings' in category and setting in category['exposed_settings']) else category[setting]


def get_exposed_settings(category):
    data = _get_settings()
    category = data[category]

    return category['exposed_settings'] if 'exposed_settings' in category else {}


def set_setting(category, setting, value, exposed=False):
    # Convert value to an int if possible
    try:
        value = int(value)
    except ValueError:
        pass

    data = _get_settings()

    if exposed:
        data[category]['exposed_settings'][setting] = value
    else:
        data[category][setting] = value

    with open(settings_file, 'w') as f:
        json.dump(data, f, indent=4)


def set_exposed_setting(category, setting, value):
    exposed_settings = get_exposed_settings(category)
    if setting in exposed_settings:
        set_setting(category, setting, value, exposed=True)
        return True
    return False


def is_channel(*args: str):
    async def predicate(ctx):
        return ctx.message.channel.name in args
    return commands.check(predicate)


def url_to_id(url: str) -> int:
    if (url is None):
        raise SyntaxError("\"{}\" is not a valid mp link".format(url))
    osu_mp_url = re.compile(r'((https://osu.ppy.sh/community/matches/)|(https://osu.ppy.sh/mp/))(?P<id>[0-9]+)')
    match = re.search(osu_mp_url, url)
    if match:
        return int(match.group('id'))
    else:
        raise SyntaxError("\"{}\" is not a valid mp link".format(url))


async def request(url: str, bot, headers: dict = {}) -> dict:
    '''Quick and dirty short-hand REST API grabber.'''
    session = await res_cog(bot).session()
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
