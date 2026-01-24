#!/bin/bash

reg=G
port=8000
num_env_workers=1
num_eval_workers=1

# sample (EUIC 2025 finals matchup, Wolfe Glick vs. Dyl Yeomans)
TEAM1="""
Flutter Mane @ Focus Sash
Ability: Protosynthesis
Level: 50
Tera Type: Normal
EVs: 4 HP / 252 SpA / 252 Spe
Timid Nature
IVs: 0 Atk
- Protect
- Icy Wind
- Moonblast
- Shadow Ball

Koraidon @ Life Orb
Ability: Orichalcum Pulse
Level: 50
Tera Type: Fire
EVs: 4 HP / 252 Atk / 252 Spe
Jolly Nature
- Protect
- Flame Charge
- Close Combat
- Flare Blitz

Amoonguss @ Mental Herb
Ability: Regenerator
Level: 50
Tera Type: Dark
EVs: 236 HP / 76 Def / 196 SpD
Sassy Nature
IVs: 0 Atk / 0 Spe
- Protect
- Rage Powder
- Sludge Bomb
- Spore

Incineroar @ Safety Goggles
Ability: Intimidate
Level: 50
Tera Type: Bug
EVs: 252 HP / 124 Def / 132 SpD
Careful Nature
IVs: 29 Spe
- Protect
- Flare Blitz
- Fake Out
- Parting Shot

Gothitelle @ Leftovers
Ability: Shadow Tag
Level: 50
Tera Type: Water
EVs: 252 HP / 196 Def / 4 SpA / 52 SpD / 4 Spe
Bold Nature
IVs: 0 Atk
- Protect
- Psychic
- Fake Out
- Taunt

Scream Tail @ Booster Energy
Ability: Protosynthesis
Level: 50
Tera Type: Dark
EVs: 252 HP / 84 Def / 68 SpD / 100 Spe
Timid Nature
IVs: 0 Atk
- Protect
- Encore
- Disable
- Perish Song
"""
TEAM2="""
megabeast:3 (Miraidon) @ Choice Specs
Ability: Hadron Engine
Level: 50
Tera Type: Fairy
EVs: 172 HP / 4 Def / 124 SpA / 4 SpD / 204 Spe
Modest Nature
- Electro Drift
- Volt Switch
- Draco Meteor
- Dazzling Gleam

hellofreak (Incineroar) (F) @ Rocky Helmet
Ability: Intimidate
Level: 50
Tera Type: Ghost
EVs: 252 HP / 140 Def / 116 SpD
Careful Nature
IVs: 11 Spe
- Flare Blitz
- Knock Off
- U-turn
- Fake Out

radicalqueen (Urshifu) (F) @ Focus Sash
Ability: Unseen Fist
Level: 50
Tera Type: Dark
EVs: 4 HP / 236 Atk / 20 Def / 4 SpD / 244 Spe
Adamant Nature
- Wicked Blow
- Sucker Punch
- Close Combat
- Detect

partypirate (Iron Hands) @ Assault Vest
Ability: Quark Drive
Level: 50
Tera Type: Poison
EVs: 76 HP / 164 Atk / 12 Def / 252 SpD
Brave Nature
IVs: 0 Spe
- Drain Punch
- Low Kick
- Heavy Slam
- Fake Out

crimsonracer (Iron Treads) @ Choice Band
Ability: Quark Drive
Level: 50
Shiny: Yes
Tera Type: Ghost
EVs: 252 Atk / 36 SpD / 220 Spe
Jolly Nature
- High Horsepower
- Iron Head
- Steel Roller
- Rock Slide

mythicdreamr (Farigiraf) (M) @ Electric Seed
Ability: Armor Tail
Level: 50
Shiny: Yes
Tera Type: Water
EVs: 228 HP / 164 Def / 116 SpD
Bold Nature
IVs: 20 Atk / 13 Spe
- Psychic
- Roar
- Trick Room
- Helping Hand
"""

start_showdown() {
    local port=$1
    (
        cd pokemon-showdown
        node pokemon-showdown start "$port" --no-security > /dev/null 2>&1 &
        echo $!
    )
}

mkdir -p "results1/saves-bc-sp-xm/2-teams"
cp bc.zip "results1/saves-bc-sp-xm/2-teams/100.zip"
echo "Starting Showdown server..."
showdown_pid=$(start_showdown "$port")
sleep 5  # give server time to start
echo "Starting training..."
python vgc_bench/train.py \
    --reg "$reg" \
    --port "$port" \
    --num_envs "$num_env_workers" \
    --num_eval_workers "$num_eval_workers" \
    --behavior_clone \
    --self_play \
    --no_mirror_match \
    --team1 "$TEAM1" \
    --team2 "$TEAM2" \
    > "debug$port.log" 2>&1
exit_status=$?
if [ $exit_status -ne 0 ]; then
    echo "Training process died with exit status $exit_status"
else
    echo "Training process finished!"
fi
kill $showdown_pid
