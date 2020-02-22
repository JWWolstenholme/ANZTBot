# Discord bot token
botToken = ''
# Which twitch channel to monitor for changing the bot's presence and announcing streams
twitchchannel = 'osuanzt'
# Osu! api key
apiKey = ''
# Shown to users to signify round in results
tourneyRound = ''
# The name of the sheet within the ANZT7S spreadsheet that contains this week's schedule
schedule_sheet_name = ''
# Twitch application client ID for making api calls
clientID = ''
# A list of referee Osu! user ids to ignore when looking at Osu! lobby scores
# This only matter if the reffs play and actually beat one of the players
referees = []
# A dict of Osu! beatmap ids to shortened mod pool. e.g. 725026: 'NM1'
pool = {}
# A dict of Osu! usernames to ISO flag codes
# Yes, I know this is bad
country = {}