# Short drama: writing a story file

Read this before writing or changing a story file. `python make.py <story> --plan` shows what a
change will run and cost, and flags any step whose stored result is invalid. `lint` in `engine/story.py`
rejects a bad story before any render.

Evidence labels used below:

- **OBSERVED**: seen in a test render.
- **REPORTED**: noted during earlier renders; no file for it is kept.
- **HEURISTIC**: plausible and consistently followed in `stories/*.json`, but never tested against an alternative.

Nothing in the HEURISTIC and REPORTED lists has been shown to cause or prevent a failure in a controlled comparison.
Two stories and a handful of takes cannot do that.

## The file is the only input

- `line` is the only place spoken words live. Prompts and captions both read it. (design rule)
- Put an anchor where something should happen, as in `师傅，@{ask}今晚还开船吗？`. Overlays bind to the
  anchor, so a rewritten line moves them with the word. Do not write seconds into an overlay. `start` and `end` are reserved.
  OBSERVED: the `promise` anchor moved 18.682 s to 18.132 s when the line changed.
  Note no overlay was bound to it in that test.
- Leave `length` out. It is worked out from a speech model fitted on real takes (HEURISTIC for new voices): chars / 4.55 + 0.72 s per
  comma or other internal punctuation, plus a 0.75 s margin, a 1.5 s latest onset and the 0.5 s closing-silence floor, so a comma
  costs real clip length. Observed fit: 11 lines, rms 0.37 s. Set it only to give a beat more room, keep it at 5 + 17k frames and within 5..209 (209 is a provisional
  limit, not a verified model limit: the longest clip rendered so far is 158 frames).
- The story is checked against a schema first (required fields, overlay types, nameplate names and roles, title text).

## What keeps two people in one shot

- A frontal portrait pulls its character to the lens, or into a solo close-up, as soon as they speak. Portraits are therefore used
  only for a silent establishing two-shot, which the build renders first (own retakes: no cut, stable last 1.5 s, a face on each
  side, judged by mediapipe, fail closed). Its closing frame is the single image every segment, the first included, takes, and the
  fixed reference of the drift check. OBSERVED in the first regression of that design: a segment 1 built straight from portraits had
  take 0 open on a solo frontal face and cut, and take 2 slide throughout. REPORTED (an early render cut to a solo close-up and a character swung round). The two-shot approach is what both
  kept stories use, and neither shows that failure.
- Give each passage one framing and hold it; do not write camera movements into a prompt (the lint rejects pans, zooms, dollies,
  cuts). REPORTED for the cut. OBSERVED that a "locked-off" prompt does not guarantee a locked frame: the noodle story pushes in
  from about 18.5 s and stays tighter, cropping a head. The drift check (below) now looks for exactly that.
- Pin screen positions in the shot sentence: "on screen-left in a side profile facing right". HEURISTIC.
- Describe held poses. Phrases about a head rotating or a body leaving the frame ("turns her head toward", "stands up",
  "rises from", "sits down", "walks out of the frame") are rejected, by whole phrase, so "chest rising and falling" is fine.
  REPORTED as a cause of head drift; the stronger claim that negatives such as "without turning" also cause it is HEURISTIC.
- Give pauses something to do: a breath, a shift of weight, a change of eyeline. A motionless hold renders as a freeze.
  REPORTED.
- End every clip with lips closed. The next clip pins those frames, so an open mouth carries over. REPORTED. The build now
  requires at least 0.5 s between the last heard word and the clip end. The prompt still asks for about 1.4 s. OBSERVED
  closing silences in the ferry takes: 0.87 s and 0.89 s, and 0.58 s after a change to the last line.

## Voice

- Only the segment's speaker gets a voice reference. Two references at once mix the voices. REPORTED, untested here.
- The reference sets who is speaking, not how. REPORTED. OBSERVED: the noodle shouted line (segment 4) was transcribed word
  for word, but its lip-to-sound correlation was -0.234 (a rough metric).
- OBSERVED: with two women, one speaker's voice-embedding similarity to herself (0.675 to 0.782) overlaps the range between the two
  speakers (0.631 to 0.743). Nothing in the build checks voice identity.

## After a build

The checks reject a take, and retake it automatically (three tries, then the build fails and publishes nothing), when:

- the picture cuts inside the clip;
- the framing drifts: 168x96 RGB against the fixed two-shot, 2 Hz, mean absolute difference above 35/255 for three
  consecutive samples;
- the blind transcript matches the script poorly (ratio and character coverage below 0.8), or a negation character
  (不 没 别 无 未 勿) appears a different number of times in script and transcript;
- speech ends less than 0.5 s before the clip end.

The establishing shot has its own check: no hard cut, the closing 1.5 s within the drift threshold of the clip's own final frame, and a
face on each of the left and right in at least 2 of 3 frames near the end. If the faces cannot be judged the take is rejected.

All thresholds are provisional. A final step transcribes the finished file's own audio from scratch and fails the build if any
line fails the dialogue check. None of this sees a dead performance, voice change, wrong-speaker delivery or lip-sync, so
look at `segN_grid.jpg` and listen before calling a video done.

Editing segment N re-renders N and everything after it, because each clip continues the previous latent. Put a change as late
in the story as the story allows. Changes to overlays, names, titles or fades touch no GPU step. A change to `overlay.py`
re-burns only `final`; a change to `align.py` rebuilds `timing` and what follows it; a change to `comfy.py`, `prompts.py` or
`review.py` re-renders.

Known limitation: overlay placement is fixed, not measured. A long title or a wider font can reach a face.
