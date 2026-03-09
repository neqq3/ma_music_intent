# MA Music Intent

`ma_music_intent` is a Home Assistant custom integration that turns a natural-language music request into a Music Assistant queue preview, and will push that queue to a target player when playable track URIs are found.

## Features

- Exposes one service: `ma_music_intent.build_queue`
- Parses a prompt into a small structured intent model
- Detects available Music Assistant service domains (`music_assistant` / `mass`)
- Chooses a basic execution strategy
- Searches for candidate tracks when a `search` service is available
- Arranges and deduplicates candidates
- Returns a structured response and optionally calls `play_media`

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
- `tracks`: arranged candidate track list
- `intent`: parsed intent snapshot
- `environment`: detected provider snapshot

## Repository

Primary remote:

- [https://github.com/neqq3/ma_music_intent](https://github.com/neqq3/ma_music_intent)
