from discord.ext import commands
from resources import is_channel, send_typing, agcm


class PoolingToolsCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['hd', 'hr', 'dt', 'fm', 'tb'])
    @is_channel('mappool')
    @send_typing
    async def nm(self, ctx):
        # Prep
        await ctx.message.delete()
        abreviations = {'nm': 'NoMod', 'hd': 'Hidden', 'hr': 'HardRock', 'dt': 'DoubleTime', 'fm': 'FreeMod', 'tb': 'TieBreaker'}
        skips = list(abreviations.values()) + ['No beatmap added']
        modpool = abreviations[ctx.invoked_with]

        # Get spreadsheet as 2d array
        agc = await agcm.authorize()
        sh = await agc.open('7S Mappool selection')
        ws = await sh.get_worksheet(0)
        raw = await ws.get_all_values()

        # Strip down 2d array to relevant maps
        # remove header row
        raw = raw[1:]
        # cut off cells on the right side
        raw = [row[:11] for row in raw]
        # Look down column 'C' looking for the specified modpool header, then collect rows until the modpool is over
        found = False
        maps = []
        for row in raw:
            if found and row[2] in skips:
                break
            if found:
                maps.append(row)
            if row[2] == modpool:
                found = True

        # Create user-readable message
        output = f'>>> __**Suggested {modpool} beatmaps:**__'
        for map in maps:
            emote = ':radio_button:' if map[0] == 'TRUE' else ':white_circle:'
            mapname = map[2] if len(map[2]) < 50 else map[2][:47] + '...'
            output += f'\n{emote} {mapname}\n             {map[4]}   |   {map[3]}*   |   {map[5]}bpm   |   {map[7]}ar   |   {map[8]}od'
        await ctx.send(output)

    @commands.command()
    @is_channel('mappool')
    @send_typing
    async def picked(self, ctx):
        # Prep
        await ctx.message.delete()
        abreviations = {'nm': 'NoMod', 'hd': 'Hidden', 'hr': 'HardRock', 'dt': 'DoubleTime', 'fm': 'FreeMod', 'tb': 'TieBreaker'}
        skips = list(abreviations.values()) + ['No beatmap added']

        # Get spreadsheet as 2d array
        agc = await agcm.authorize()
        sh = await agc.open('7S Mappool selection')
        ws = await sh.get_worksheet(0)
        raw = await ws.get_all_values()

        # Strip down 2d array to relevant maps
        # remove header row
        raw = raw[1:]
        # cut off cells on the right side
        raw = [row[:11] for row in raw]

        output = f'>>> __**Selected beatmaps**__'

        # Look down column 'C' looking for the specified modpool header, then collect rows until the modpool is over
        for modpool in list(abreviations.values()):
            output += f'\n**{modpool}:**'
            found = False
            for row in raw:
                if found and row[2] in skips:
                    break
                if found and row[0] == 'TRUE':
                    emote = ':radio_button:' if row[0] == 'TRUE' else ':white_circle:'
                    mapname = row[2] if len(row[2]) < 50 else row[2][:47] + '...'
                    output += f'\n{emote} {mapname}\n             {row[4]}   |   {row[3]}*   |   {row[5]}bpm   |   {row[7]}ar   |   {row[8]}od'
                if row[2] == modpool:
                    found = True

        await ctx.send(output)


def setup(bot):
    bot.add_cog(PoolingToolsCog(bot))
