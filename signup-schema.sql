create table signups (
    discord_id numeric(21) primary key,
    osu_id numeric(14) unique not null
);

create table settings (
    -- Table should only ever have one row. This and the constraint ensure there is only ever 0 or 1 row.
    onerow bool primary key default TRUE,
    -- message to watch for reactions on to signify user wants to register
    watch_message_link numeric(21),
    constraint onerow check (onerow)
);
insert into settings values (TRUE, NULL);