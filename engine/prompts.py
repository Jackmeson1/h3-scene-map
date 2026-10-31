"""Prompt formats. A format turns one story segment into a model prompt; a segment's own `prompt` overrides it."""

from .script import FPS, HEAD_FRAMES, LEAD_IN, MIN_CLOSING_SILENCE, speech_seconds, spoken


def tc(sec: float) -> str:
    return f"{int(sec // 60):02d}:{sec % 60:06.3f}"


def planned_seconds(line: str) -> float:
    """The fitted time to say the line (script.speech_seconds). The prompt's timecodes, the clip length and the closing-silence gate all
    derive from this one model."""
    return speech_seconds(line)


def cast_prompt(story: dict, who: dict) -> str:
    speak = planned_seconds(who["cast_line"])
    return (
        "summary:\n"
        f"{who['desc'][0].upper()}{who['desc'][1:]} stands alone in {story['scene']}, facing the camera slightly off-axis, and says one short line.\n\n"
        "detailed_description:\n"
        f"r34l1sm, Facial Realism, {story['style']}.\n"
        f"[Shot 1] The camera holds a static medium shot of {who['desc']}, centered, chest up, with a clear view of the face. "
        f"During 00:00.000–00:00.500, {who['they']} keeps {who['their']} mouth closed and looks steadily ahead. "
        f"During 00:00.500–{tc(0.5 + speak)}, {who['they']} speaks clearly in {who['voice']}: <d>[Mandarin]{who['cast_line']}</d> "
        f"Immediately after, {who['they']} closes {who['their']} lips and breathes quietly until the end. No additional speech, no subtitles.\n\n"
        "overall_soundscape:\nQuiet, close, dry room tone so the voice is clean and in the foreground.\n\n"
        "non_diegetic_music:\nN/A"
    )


def establish_prompt(story: dict, length: int) -> str:
    """A silent two-shot from the two character portraits: no voice reference, no dialogue. Same shot sentence and held-pose language as
    two_person_static, so its closing frame is the framing every later segment keeps."""
    left, right = story["characters"]["left"], story["characters"]["right"]
    dur = length / FPS
    return (
        "subject_definitions:\n"
        f"<Subject 1> is {left['desc']}, in <Picture 1>.\n"
        f"<Subject 2> is {right['desc']}, in <Picture 2>.\n\n"
        "summary:\n"
        f"[reference generation] Inside {story['scene']}, <Subject 1> stands on the left and <Subject 2> stands on the right, "
        "facing each other in silence. Neither speaks.\n\n"
        "retention_analysis:\n"
        "<Subject 1> (appears in [Shot 1]): fully_preserved - exact facial bone structure, skin texture, hair and clothing from <Picture 1> are strictly preserved on the left side of the frame facing right.\n"
        "<Subject 2> (appears in [Shot 1]): fully_preserved - exact facial bone structure, skin texture, hair and clothing from <Picture 2> are strictly preserved on the right side of the frame facing left.\n\n"
        "detailed_description:\n"
        f"r34l1sm, Facial Realism, {story['style']}. Keep one coherent face belonging only to <Subject 1> on the left and one different coherent face belonging only to <Subject 2> on the right.\n"
        "[Shot 1] One continuous locked-off take, framing <Subject 1> on screen-left in a side profile facing right and <Subject 2> on screen-right in a side profile facing left in a balanced medium two-shot, each looking only at the other with head held level. "
        f"During 00:00.000–{tc(dur)}, both characters keep their mouths closed, breathe quietly and hold a silent look at each other, with only a slow blink and a small settling of the shoulders. No speech, no subtitles.\n\n"
        f"overall_soundscape:\n{story['soundscape']} No voices, no speech.\n\n"
        "non_diegetic_music:\nN/A"
    )


def two_person_static(story: dict, seg: dict, length: int, first: bool) -> str:
    """Every segment takes the one establishing two-shot as its only image. The first opens the scene from it; later ones continue the
    previous clip. A frontal portrait pulls its character back to face the lens, or into a solo close-up, once they speak, which is why
    portraits are only used for the silent establishing shot."""
    left, right = story["characters"]["left"], story["characters"]["right"]
    line = spoken(seg["line"])
    sk = 1 if seg["speaker"] == "left" else 2
    lk = 3 - sk
    speaker = left if sk == 1 else right
    dur = length / FPS
    t0 = (0.0 if first else HEAD_FRAMES / FPS) + LEAD_IN
    t1 = min(t0 + planned_seconds(seg["line"]), dur - MIN_CLOSING_SILENCE)
    opening = "Opening the scene in the exact same static medium two-shot as <Picture 1>, inside" if first else "Seamlessly continuing the exact same static medium two-shot inside"
    keep = "keeping the exact same framing as <Picture 1>, framing" if first else "continuing the exact same framing as the previous moment, framing"
    pic = "<Picture 1>"
    return (
        "subject_definitions:\n"
        f"<Subject 1> is {left['desc']}, the person on screen-left in {pic}.\n"
        f"<Subject 2> is {right['desc']}, the person on screen-right in {pic}.\n"
        f"<Audio 1> is the voice-timbre reference for <Subject {sk}> (S{sk}), providing only {speaker['their']} physical vocal identity "
        "and not the target dialogue or emotional delivery.\n\n"
        "summary:\n"
        f"[reference generation + audio reference] {opening} {story['scene']}, <Subject 1> stands on the left and <Subject 2> stands on the right, "
        f"facing each other. <Subject {sk}> (S{sk}) {seg['intent']} using the vocal timbre of <Audio 1>, while <Subject {lk}> listens in silence.\n\n"
        "retention_analysis:\n"
        f"<Subject 1> (appears in [Shot 1]): fully_preserved - exact facial bone structure, skin texture, hair and clothing from {pic} are strictly preserved on the left side of the frame facing right.\n"
        f"<Subject 2> (appears in [Shot 1]): fully_preserved - exact facial bone structure, skin texture, hair and clothing from {pic} are strictly preserved on the right side of the frame facing left.\n"
        f"<Audio 1>: reference - its physical speaker timbre guides <Subject {sk}> (S{sk})'s newly performed Mandarin dialogue without copying the original signal.\n\n"
        "detailed_description:\n"
        f"r34l1sm, Facial Realism, {story['style']}. Keep one coherent face belonging only to <Subject 1> on the left and one different coherent face belonging only to <Subject 2> on the right.\n"
        f"[Shot 1] One continuous locked-off take, {keep} <Subject 1> on screen-left in a side profile facing right and <Subject 2> on screen-right in a side profile facing left in a balanced medium two-shot, each looking only at the other with head held level. "
        f"During 00:00.000–{tc(t0)}, {seg['before']}, and both characters keep their mouths closed. "
        f"During {tc(t0)}–{tc(t1)}, <Subject {sk}> (S{sk}) speaks in {seg['delivery']}, referenced from <Audio 1>: <d>[Mandarin]{line}</d> "
        f"{speaker['they'].capitalize()} says this line once and completes it by {tc(t1)} while <Subject {lk}> listens silently with a closed mouth. "
        f"Immediately during {tc(t1)}–{tc(dur)}, {seg['after']}, and both hold a silent look with mouths closed until the end. No additional speech, no subtitles.\n\n"
        f"overall_soundscape:\n{story['soundscape']} {seg.get('sound', '')} <Subject {sk}> (S{sk}) speaks clearly in the foreground.\n\n"
        "non_diegetic_music:\nN/A"
    )


FORMATS = {"two_person_static": two_person_static}


def segment_prompt(story: dict, seg: dict, length: int, first: bool) -> str:
    if "prompt" in seg:
        return seg["prompt"]
    return FORMATS[story.get("format", "two_person_static")](story, seg, length, first)
