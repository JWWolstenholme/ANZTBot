# Discord bot token
botToken = ''

# Twitch settings
# Which twitch channel to monitor for changing the bot's presence and announcing streams
twitchchannel = 'osuanzt'
# Twitch application client ID and secret for making api calls
clientID = ''
clientSecret = ''

# Osu! api key
apiKey = ''

# Match Result tourney settings
# Shown to users to signify round in results. Recommend an acronym like RO16 or GS.
tourneyRound = 'GS'
# Tells the bot which range of cells to look at for the current mappool, with our specific sheets
poolRound = 0
# The name of the ANZT7S spreadsheet that contains our referee's inputs
sheet_file_name = 'ANZT8S Bracket Stage Staff Sheet'
# The name of the worksheet within the spreadsheet defined above that contains the schedule for this week
schedule_sheet_name = 'Finals Schedule'
# A list of referee Osu! user ids to ignore when looking at Osu! lobby scores
# This only matters if the reffs play and actually beat one of the players
referees = []

# Tourney Registering settings
# encryption key as generated by Fernet.generate_key()
# Used to prevent users from impersonating other discord users in the OAuth process
key = b''
osu_app_client_id = ''
osu_app_client_secret = ''
redirect_url = 'https://osuanzt.com/register/'
signup_close_date = 'June 15th'
forum_post_url = ''
allowed_countries = ['NZ', 'AU']

# Database credentials - Not currently in use
# dbname = ''
# dbuser = ''
# dbpass = ''
# dbhost = ''
# dbport = ''
