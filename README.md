# MA Music Intent

`ma_music_intent` is a Home Assistant custom integration that turns a complex natural-language music request into a temporary Music Assistant queue. It uses Home Assistant's configured AI conversation agent to understand intent, then lets an execution planner choose how to expand, search, blend, arrange, and play tracks in the current environment.

## Features

- Exposes one service: `ma_music_intent.build_queue`
- Reuses Home Assistant conversation / LLM agents instead of adding a separate model stack
- Parses natural language into an execution-oriented music intent as an intermediate representation
- Detects available Music Assistant service domains (`music_assistant` / `mass`)
- Chooses between recommendation expansion, search expansion, library-only degradation, or multi-provider blending
- Builds a candidate pool from AI seeds, candidate hints, keywords, and provider-native expansion when available
- Arranges and deduplicates candidates before playback
- Pushes a playable queue to Music Assistant by starting playback and queueing additional tracks when possible

## Install

Copy `custom_components/ma_music_intent` into your Home Assistant `custom_components` directory and restart Home Assistant.

## Service usage

```yaml
service: ma_music_intent.build_queue
response_variable: result
data:
  prompt: 给我来 30 首适合晚上写代码的歌，中文优先，别太吵。
  target_player: media_player.living_room
  count: 30
  mode: auto
```

The service returns a response payload with:

- `executed`: whether queue push was attempted successfully
- `message`: outcome summary
- `strategy`: selected execution strategy
- `plan`: execution plan snapshot, including provider routes and queue constraints
- `tracks`: arranged candidate track list
- `intent`: parsed intent snapshot
- `environment`: detected provider snapshot

## Repository

Primary remote:

- [https://github.com/neqq3/ma_music_intent](https://github.com/neqq3/ma_music_intent)
