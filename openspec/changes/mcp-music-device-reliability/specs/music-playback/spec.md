## ADDED Requirements

### Requirement: Approved track is the track played
After `music_search` returns `Encontrada: <title>`, a following `music_play` or `music_queue` whose query equals that exact title SHALL use the already resolved track without searching again. A resolved track SHALL be reusable for 10 minutes; at most the 20 most recent are kept. Any other query SHALL be searched normally.

#### Scenario: Reuse after search
- **WHEN** `music_search("x")` returns title T and `music_play("T")` follows within 10 minutes
- **THEN** T is loaded without another resolver call

#### Scenario: Different query
- **WHEN** `music_play("other")` is called
- **THEN** the resolver is called for "other"

### Requirement: Expired track is refreshed, never replaced
When the remembered track's validity has elapsed, playback SHALL resolve the title again and accept the result only when its title equals the remembered title; otherwise it SHALL answer `Error: ...` and play nothing.

#### Scenario: Expired and same recording
- **WHEN** the remembered track is 11 minutes old and re-resolving returns the same title
- **THEN** the refreshed track plays

#### Scenario: Expired and different recording
- **WHEN** re-resolving returns another title
- **THEN** nothing plays and the answer starts with `Error:`
