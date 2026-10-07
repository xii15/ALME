# ALME
Ableton Live MIDI Exporter - exports MIDI tracks including tempo and time-signature changes

# Ableton Live MIDI Exporter

A lightweight Python utility for exporting MIDI tracks from an **Ableton Live Set (`.als`)** or an **Ableton XML export (`.xml`)** as independent standard MIDI (`.mid`) files.

The script provides a simple macOS graphical interface for selecting the Ableton file, choosing the destination folder, and selecting which MIDI tracks to export.

## Features

* Supports Ableton Live `.als` files
* Supports Ableton XML `.xml` files
* Exports selected MIDI tracks as individual `.mid` files
* Preserves:

  * MIDI note pitch
  * Note start position
  * Note duration
  * Note-on velocity
  * Note-off velocity
  * Tempo
  * Time signatures
  * Track names
* Converts Ableton's floating-point velocities to standard MIDI integers
* Prevents unrelated MIDI data, such as **Groove Pool clips**, from being exported accidentally
* Automatically avoids overwriting existing MIDI files
* Uses standard MIDI timing with 960 ticks per quarter note

## Velocity Handling

Ableton Live can store MIDI note velocities as floating-point values, for example:

```text
65.5866699
81.453331
127.0
```

Standard MIDI note velocity is an integer from **0–127**.

The script therefore removes the decimal portion rather than rounding:

```text
65.5866699 → 65
81.453331  → 81
127.0      → 127
```

This preserves the original Ableton velocity value as closely as possible within the integer MIDI format.

The script also preserves Ableton's `OffVelocity` values for MIDI note-offs.

## Avoiding Groove Pool Data

Ableton Live's XML structure can contain `MidiClip` elements that are not part of an actual MIDI track. For example, MIDI material belonging to the **Groove Pool** can also contain `MidiNoteEvent` elements.

A simple search for all `MidiClip` elements in the XML could therefore export MIDI that does not belong to the user's tracks.

This script avoids that problem by searching for MIDI clips **only within actual `MidiTrack` elements**.

As a result, only MIDI data belonging to the selected tracks is exported.

## Input

The script accepts either:

* `.als` — Ableton Live Set
* `.xml` — Ableton XML file

Ableton `.als` files are normally gzip-compressed XML. The script reads this format directly and also includes a ZIP fallback.

## Output

Each selected MIDI track is exported as a separate MIDI file.

For example:

```text
My Ableton Project.als

        ↓

Export Folder/
├── Piano.mid
├── Violin.mid
├── Bass.mid
└── Percussion.mid
```

If a file with the same name already exists, the script does not overwrite it:

```text
Piano.mid
Piano_2.mid
Piano_3.mid
```

## Graphical Interface

When the script is launched, it provides macOS dialogs to:

1. Select an Ableton `.als` or `.xml` file
2. Select the export folder
3. Choose which MIDI tracks to export
4. Export the selected tracks

The script does not require Ableton Live to be running.

## Requirements

* Python 3
* [`mido`](https://mido.readthedocs.io/)
* Tkinter

Install Mido with:

```bash
pip install mido
```

On macOS, Python can be installed from [python.org](https://www.python.org/).

## Usage

Run:

```bash
python3 ableton_to_midi_gui.py
```

Then follow the graphical dialogs.

The script will ask you to select the Ableton file and the destination folder, followed by the MIDI tracks to export.

When selecting tracks, you can enter individual track numbers separated by commas:

```text
1,3,5
```

or export all MIDI tracks:

```text
ALL
```

## MIDI Timing

Ableton beat positions are converted to MIDI ticks using:

```text
960 ticks per quarter note
```

This provides a high-resolution MIDI representation while maintaining the original musical positions.

## What the Script Does Not Do

The exporter is intended primarily as a **MIDI data converter**, not as a complete Ableton Live project renderer.

It does not attempt to reproduce Ableton-specific features such as:

* Audio tracks
* Audio clips
* Instrument devices
* MIDI effects
* Automation of instruments or effects
* Ableton-specific groove processing
* Sample playback
* VST/AU instruments
* Track mixing
* Panning
* Volume automation

The purpose is to extract the underlying MIDI information from Ableton's XML representation and create clean, standard MIDI files.

## License

MIT License
