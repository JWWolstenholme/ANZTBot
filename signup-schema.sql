create table signups (
    discord_id numeric(21) primary key,
    osu_id numeric(14) unique not null
);

create table settings (
    -- Table should only ever have one row
    -- message to watch for reactions on to signify user wants to register
    message_link text
)