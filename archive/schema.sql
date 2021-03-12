create table players (
    osu_id numeric(14) primary key,
    osu_username text,
    discord_id numeric(21)
);

create table staff (
    staff_osu_id numeric(14) primary key,
    staff_osu_username text,
    staff_discord_id numeric(21)
);

create table lobbies (
    lobby_id numeric(3) primary key,
    time timestamp,
    staff_osu_id numeric(13) references staff
);

create table lobby_signups (
    osu_id numeric(14) primary key references players,
    lobby_id numeric(3) references lobbies
);

create table persistent_messages (
    message_id numeric(21) primary key,
    day date,
    thumbnail_url text
);

create or replace function check_lobby_capacity()
returns trigger as
$body$
begin
    if (select count(*) from lobby_signups where lobby_id=new.lobby_id) > 15
    then 
        raise exception 'lobby is full';
    end if;
    return new;
end;
$body$
language plpgsql;

create trigger tr_check_lobby_capacity
before insert or update on lobby_signups
for each row execute procedure check_lobby_capacity();

copy players from '/home/anztbot/players.csv' delimiter ',' csv header;