#!/usr/bin/env python3
"""
Export selected MIDI tracks from an Ableton Live Set (.als) or Ableton XML
(.xml) to standalone MIDI files.

Preserves:
- note pitch
- note start time
- note duration
- note-on velocity
- note-off velocity
- MIDI pitch bend
- MIDI CC1 (modulation), CC7 (channel volume), CC11 (expression), and CC64 (sustain), when present as clip automation
- tempo
- time signatures

Ableton stores note velocities as floating-point values, e.g.
65.5866699. MIDI velocities are integers, so the decimal part is removed:
65.5866699 -> 65.

The exporter only reads MidiClip elements that belong to actual MidiTrack
elements. This prevents unrelated clips, such as Groove Pool MIDI data,
from being exported accidentally.
"""

import gzip
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from mido import MidiFile, MidiTrack, Message, MetaMessage, bpm2tempo


TPB = 960


def beats_to_ticks(beats):
    """Convert Ableton beat positions to MIDI ticks."""
    return int(round(beats * TPB))


def load_xml(source_path):
    """
    Load an Ableton .als or .xml file and return its XML root.

    .als files are normally gzip-compressed XML.
    .xml files are read directly.
    ZIP-compressed Ableton containers are also supported as a fallback.
    """
    source_path = Path(source_path)

    if source_path.suffix.lower() == ".xml":
        return ET.parse(source_path).getroot()

    # Normal Ableton Live .als format: gzip-compressed XML.
    try:
        with gzip.open(source_path, "rb") as source:
            return ET.parse(source).getroot()
    except (OSError, EOFError):
        pass

    # Fallback for ZIP-based containers.
    with zipfile.ZipFile(source_path) as archive:
        members = archive.namelist()
        if not members:
            raise ValueError("The Ableton file contains no XML data.")

        # Prefer an XML-looking member.
        xml_members = [name for name in members if name.lower().endswith(".xml")]
        member = xml_members[0] if xml_members else members[0]

        with archive.open(member) as source:
            return ET.parse(source).getroot()


def get_track_name(track_node, default="Track"):
    """Return an Ableton MIDI track's effective name."""
    name_node = track_node.find("./Name/EffectiveName")

    if name_node is None:
        return default

    return name_node.attrib.get("Value", default)


def read_tempo_and_signatures(root):
    """Extract tempo and time-signature automation from the Ableton XML."""
    tempos = []
    signatures = []

    envelope_path = ".//MainTrack/AutomationEnvelopes/Envelopes/AutomationEnvelope"

    for envelope in root.findall(envelope_path):
        pointee = envelope.find("./EnvelopeTarget/PointeeId")

        if pointee is None:
            continue

        parameter_id = pointee.attrib.get("Value")

        if parameter_id == "8":
            for event in envelope.findall(".//FloatEvent"):
                tempos.append(
                    (
                        float(event.attrib["Time"]),
                        float(event.attrib["Value"]),
                    )
                )

        elif parameter_id == "10":
            for event in envelope.findall(".//EnumEvent"):
                signatures.append(
                    (
                        float(event.attrib["Time"]),
                        int(event.attrib["Value"]),
                    )
                )

    if not tempos:
        tempos = [(0.0, 120.0)]

    return tempos, signatures


def decode_ableton_timesig(ts_id):
    """Convert an Ableton time-signature ID to (numerator, denominator)."""
    ranges = (
        (99, 198, 98, 2),
        (198, 297, 197, 4),
        (297, 396, 296, 8),
        (396, 495, 395, 16),
    )

    for lower, upper, offset, denominator in ranges:
        if lower <= ts_id < upper:
            return ts_id - offset, denominator

    raise ValueError(f"Unknown Ableton time signature ID: {ts_id}")


def build_conductor_track(mid, tempos, signatures):
    """Add tempo and time-signature events to a MIDI conductor track."""
    track = MidiTrack()
    mid.tracks.append(track)

    events = [
        (max(0.0, beat), 0, "tempo", bpm)
        for beat, bpm in tempos
    ]

    events.extend(
        (max(0.0, beat), 1, "signature", signature)
        for beat, signature in signatures
    )

    events.sort(key=lambda event: (event[0], event[1]))

    last_tick = 0

    for beat, _, kind, value in events:
        tick = beats_to_ticks(beat)
        delta = tick - last_tick
        last_tick = tick

        if kind == "tempo":
            track.append(
                MetaMessage(
                    "set_tempo",
                    tempo=bpm2tempo(value),
                    time=delta,
                )
            )
        else:
            numerator, denominator = decode_ableton_timesig(value)

            track.append(
                MetaMessage(
                    "time_signature",
                    numerator=numerator,
                    denominator=denominator,
                    time=delta,
                )
            )

    track.append(MetaMessage("end_of_track", time=0))


def midi_int(value, default):
    """
    Convert an Ableton numeric value to a MIDI integer.

    Decimal values are truncated, not rounded:
    65.5866699 -> 65.
    """
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        value = default

    return max(0, min(127, value))


def collect_note_events(track_node):
    """
    Collect note events from the actual MIDI clips belonging to this track.

    Returns tuples:
        (absolute_beat, order, event_type, pitch, velocity)
    """
    events = []

    # IMPORTANT:
    # Search only inside this MidiTrack. This avoids picking up unrelated
    # MidiClip elements elsewhere in the Ableton XML, such as Groove Pool data.
    for clip in track_node.findall(".//MidiClip"):
        clip_start = float(clip.attrib.get("Time", 0))

        for keytrack in clip.findall("./Notes/KeyTracks/KeyTrack"):
            midi_key = keytrack.find("./MidiKey")

            if midi_key is None:
                continue

            pitch = int(midi_key.attrib["Value"])

            for note in keytrack.findall("./Notes/MidiNoteEvent"):
                start = clip_start + float(note.attrib.get("Time", 0))
                duration = float(note.attrib.get("Duration", 1))
                end = start + duration

                # Ableton stores these as floating-point values.
                # Example: 81.453331 -> MIDI velocity 81.
                velocity = midi_int(
                    note.attrib.get("Velocity"),
                    100,
                )

                # Preserve Ableton's OffVelocity as well.
                off_velocity = midi_int(
                    note.attrib.get("OffVelocity"),
                    0,
                )

                events.append(
                    (start, 0, "on", pitch, velocity)
                )
                events.append(
                    (end, 1, "off", pitch, off_velocity)
                )

    return sorted(events, key=lambda event: (event[0], event[1]))


def collect_controller_events(track_node):
    """Read MIDI controller automation stored in Ableton MIDI clips.

    Ableton stores these events as ClipEnvelope/FloatEvent points. The
    ControllerTargets index identifies the MIDI message: index 0 is pitch
    bend; indices 3 and above map to CC number index - 2. Thus CC1, CC7,
    CC11, and CC64 are indices 3, 9, 13, and 66 respectively.

    Ableton's very early sentinel points (typically Time=-63072000) are
    initial-value markers, not actual events in the clip, and are omitted.
    """
    events = []
    midi_controllers = track_node.find(".//MidiControllers")
    if midi_controllers is None:
        return events

    target_ids = {}
    for target in midi_controllers:
        if target.tag.startswith("ControllerTargets."):
            target_ids[target.attrib.get("Id")] = target.tag

    for clip in track_node.findall(".//MidiClip"):
        clip_start = float(clip.attrib.get("Time", 0))
        for envelope in clip.findall("./Envelopes/Envelopes/ClipEnvelope"):
            pointee = envelope.find("./EnvelopeTarget/PointeeId")
            if pointee is None:
                continue
            target_tag = target_ids.get(pointee.attrib.get("Value"))
            if not target_tag:
                continue
            try:
                target_index = int(target_tag.split(".")[-1])
            except ValueError:
                continue

            if target_index == 0:
                message_type = "pitchwheel"
                controller_number = None
            elif target_index >= 3:
                message_type = "control_change"
                controller_number = target_index - 2
                if controller_number < 0 or controller_number > 127:
                    continue
            else:
                # Channel pressure and polyphonic aftertouch are not part of
                # the requested controller set, so leave them untouched.
                continue

            automation = envelope.find("./Automation/Events")
            if automation is None:
                continue
            for point in automation:
                if point.tag not in ("FloatEvent", "EnumEvent"):
                    continue
                try:
                    beat = float(point.attrib.get("Time", 0))
                    raw_value = float(point.attrib["Value"])
                except (KeyError, TypeError, ValueError):
                    continue
                if beat < 0:
                    continue

                absolute_beat = clip_start + beat
                if message_type == "pitchwheel":
                    # Ableton's pitch-bend envelope uses the unsigned MIDI
                    # range 0..16383; Mido uses the signed range -8192..8191.
                    value = max(-8192, min(8191, int(raw_value) - 8192))
                    events.append((absolute_beat, 2, "pitchwheel", None, value))
                else:
                    value = midi_int(raw_value, 0)
                    events.append((absolute_beat, 2, "control_change", controller_number, value))

    return events


def collect_all_events(track_node):
    """Collect note events plus pitch-bend and CC automation points."""
    events = collect_note_events(track_node)
    events.extend(collect_controller_events(track_node))
    return sorted(events, key=lambda event: (event[0], event[1]))


def add_midi_events(track, events):
    """Write absolute beat positions as delta-timed MIDI events."""
    last_tick = 0

    for beat, _, event_type, number, value in events:
        tick = beats_to_ticks(beat)
        delta = tick - last_tick
        last_tick = tick

        if event_type == "on":
            message = Message("note_on", note=number, velocity=value, time=delta)
        elif event_type == "off":
            message = Message("note_off", note=number, velocity=value, time=delta)
        elif event_type == "control_change":
            message = Message("control_change", control=number, value=value, time=delta)
        elif event_type == "pitchwheel":
            message = Message("pitchwheel", pitch=value, time=delta)
        else:
            continue
        track.append(message)

    track.append(MetaMessage("end_of_track", time=0))


def choose_tracks(track_names):
    """Ask the user which tracks should be exported."""
    listing = "\n".join(
        f"{index}. {name}"
        for index, name in enumerate(track_names, start=1)
    )

    answer = simpledialog.askstring(
        "Track Selection",
        f"Available MIDI Tracks:\n\n{listing}\n\n"
        "Enter track numbers separated by commas, or type ALL",
    )

    if not answer:
        raise SystemExit

    if answer.strip().upper() == "ALL":
        return set(track_names)

    selected = set()

    for item in answer.split(","):
        item = item.strip()

        if item.isdigit():
            index = int(item)

            if 1 <= index <= len(track_names):
                selected.add(track_names[index - 1])

    return selected


def unique_output_path(folder, track_name):
    """
    Create a non-destructive output filename.

    If Track.mid already exists, use Track_2.mid, Track_3.mid, etc.
    """
    folder = Path(folder)
    base = folder / f"{track_name}.mid"

    if not base.exists():
        return base

    counter = 2

    while True:
        candidate = folder / f"{track_name}_{counter}.mid"

        if not candidate.exists():
            return candidate

        counter += 1


def export_track(track_node, export_folder, tempos, signatures):
    """Convert one Ableton MIDI track to a standalone MIDI file."""
    track_name = get_track_name(track_node)

    midi = MidiFile(type=1, ticks_per_beat=TPB)

    build_conductor_track(midi, tempos, signatures)

    note_track = MidiTrack()
    midi.tracks.append(note_track)

    note_track.append(
        MetaMessage(
            "track_name",
            name=track_name,
            time=0,
        )
    )

    events = collect_all_events(track_node)
    add_midi_events(note_track, events)

    output_file = unique_output_path(export_folder, track_name)
    midi.save(output_file)

    note_count = sum(1 for event in events if event[2] == "on")
    controller_count = sum(1 for event in events if event[2] in ("control_change", "pitchwheel"))
    return output_file.name, note_count, controller_count


def main():
    root_ui = tk.Tk()
    root_ui.withdraw()

    try:
        source_file = filedialog.askopenfilename(
            title="Select Ableton Live Set or XML",
            filetypes=[
                ("Ableton Live Set / XML", "*.als *.xml"),
                ("Ableton Live Set", "*.als"),
                ("XML File", "*.xml"),
                ("All Files", "*.*"),
            ],
        )

        if not source_file:
            return

        export_folder = filedialog.askdirectory(
            title="Select Export Folder"
        )

        if not export_folder:
            return

        root = load_xml(source_file)

        midi_tracks = root.findall(".//Tracks/MidiTrack")

        if not midi_tracks:
            raise ValueError("No MIDI tracks were found in the selected file.")

        track_names = [
            get_track_name(track, f"Track {index}")
            for index, track in enumerate(midi_tracks, start=1)
        ]

        selected = choose_tracks(track_names)

        if not selected:
            messagebox.showwarning(
                "No Tracks Selected",
                "No MIDI tracks were selected for export.",
            )
            return

        tempos, signatures = read_tempo_and_signatures(root)

        exported = []

        for track in midi_tracks:
            name = get_track_name(track)

            if name in selected:
                filename, note_count, controller_count = export_track(
                    track,
                    export_folder,
                    tempos,
                    signatures,
                )

                exported.append(
                    f"{filename}  ({note_count} notes, {controller_count} controller events)"
                )

        messagebox.showinfo(
            "Finished",
            "Exported files:\n\n" + "\n".join(exported),
        )

    except Exception as error:
        messagebox.showerror("Error", str(error))
        raise

    finally:
        root_ui.destroy()


if __name__ == "__main__":
    main()
