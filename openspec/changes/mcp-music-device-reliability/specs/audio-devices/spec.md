## ADDED Requirements

### Requirement: Honest device selection
Selecting an audio device SHALL only match devices that can serve the requested kind (input devices for input, output devices for output). A name SHALL match exactly first, then ignoring case and surrounding whitespace. When the requested device is not found, the default device SHALL be used and the `audio_devices` event SHALL carry the corresponding `input_fallback_warning` or `output_fallback_warning` naming the requested device. Selecting `null` (default) SHALL produce no warning.

#### Scenario: Missing output device
- **WHEN** the user selects output device "Foo" and no output device named "Foo" exists
- **THEN** the default output is used and `output_fallback_warning` names "Foo"

#### Scenario: Device of the wrong kind
- **WHEN** an input-only device name is selected as output
- **THEN** it does not match, the default output is used and a warning is published

#### Scenario: Case difference
- **WHEN** "usb mic" is selected and the device is called "USB Mic"
- **THEN** it matches and no warning is published
