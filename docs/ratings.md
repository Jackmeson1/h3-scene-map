# Take-by-take ratings

GPT-6 wrote this review from 48 frame sheets (two frames per second) plus extra frames around cuts, contacts and joins.
It is printed as written, apart from plain names for scenes and a key to the take numbers. Nobody had heard the audio.

Correction to the review: it found no split screen, but take 2201 of the four-segment scene ends in one, in segment 4. I
saw it by eye, and confirmed it at full resolution and with `scripts/split_scan.py`. That moves the take from fixable to
failed, so the totals in the README are 19 usable, 8 fixable and 6 failed, against 19, 9 and 5 below.

Take numbers are the end of the seed: `11` is seed `2026110011`, `101` is `2026110101`. The first digits mark the scene.

---

The workflow produces usable dramatic footage more reliably than it obeys its precise promises: **19 of 33 takes are usable, 9 fixable, and 5 failed** on this visual review. Restrained dialogue, reactions, recognizable faces, and tea pouring are its strongest results. Exact speech windows, guaranteed headroom, immediate action starts, and sustained full-body framing are unreliable. The fight joins themselves work better than the choreography and framing guarantees. The four-segment scene approximately reproduces the reported render time, but not its promised continuous composition or female volume increase. Its profile-lock result is inconclusive evidence against the original workflow because the end-frame lock port changed materially.

Ratings below are editorial judgments from all 48 sheets plus additional frames around cuts, contacts, joins, and endings; audio was not heard. **U = usable, X = fixable, F = failed.** Seed suffixes identify the indexed seeds: `11` means `2026110011`, `101` means `2026110101`; the four-segment scene uses `2201/3201/4201`. A/B and four-segment grades are listed individually.

| Scene | Every clip’s grade | U / X / F, out of 3 seeds | Render minutes per seed; total | Main reason |
|---|---|---:|---|---|
| Monologue | 11 U; 12 U; 13 U | 3 / 0 / 0 | 2.45–2.50; **7.45** | Convincing close-ups; tight crown crops remain editorially acceptable. |
| Two-shot | 21 U; 22 F; 23 U | 2 / 0 / 1 | 2.71–2.75; **8.21** | 22 cuts from Chen’s reference composition to Lin alone; never supplies the required two-shot. |
| Reverse pair | 31 A/B U/U; 32 U/U; 33 U/U | 3 / 0 / 0 | 5.40–5.45; **16.30** | Recognizable characters and readable reverses; foreground faces sometimes dominate. |
| Walk and talk | 41 U; 42 U; 43 U | 3 / 0 / 0 | 4.10; **12.31** | Continuous, credible walking; tracking varies in scale and steadiness. |
| Outburst | 51 U; 52 X; 53 U | 2 / 1 / 0 | 2.75; **8.25** | Strong visible confrontation; 52 generates unwanted subtitles. |
| Stand-up | 61 X; 62 X; 63 X | 0 / 3 / 0 | 2.75; **8.25** | Camera compensation arrives after the rising head crosses the top edge. |
| Reaction | 71 U; 72 U; 73 U | 3 / 0 / 0 | 1.30; **3.90** | Readable surprise and stable faces; open-mouth endings work dramatically. |
| Fight | 81 A U*/B X; 82 A U*/B F; 83 A U*/B U | 1 / 1 / 1 | 9.50–9.60; **28.66** | 83 gives readable action; 81’s trap is questionable; 82’s continuation becomes mannequin-like. |
| Dance | 91 F; 92 F; 93 X | 0 / 1 / 2 | 8.35–8.40; **25.11** | 91–92 lose substantial choreography to framing; 93 chiefly needs its cropped leap repaired. |
| Tea | 101 U; 102 U; 103 X | 2 / 1 / 0 | 4.00–4.05; **12.10** | Coherent pouring; 103 pushes into an awkward partial-face crop. |
| Four-segment | 2201: U/U/U*/X; 3201: U/U/X/U; 4201: U/U/F/U | 0 / 2 / 1 | 12.75–12.85; **38.36** | 2201 crops Chen; 3201 has a questionable setup change; 4201 resets staging and props in segment 3. |

\* Trim the reference opening from each fight A, approximately the first second. Trim the brief inherited opening before four-segment 2201 segment 3’s jump. These trims lose no essential action. Four-segment singles can be usable coverage individually while failing the promised continuous two-shot.

The following table covers every indexed claim. “All” means all three seeds. Word timing comes from the blind Whisper `words` measurements in `meta.json`, not listening; it does not establish lip sync. Volume figures are whole-track ffmpeg means, including silence and effects, rather than isolated vocal loudness.

| Scene | Claim | Rating and evidence |
|---|---|---|
| Monologue | Lips follow line; finishes within 0.800–4.500 | **Failed timing; sync not judged.** Ends measured at 5.55/5.57/5.51 s for 11/12/13. |
| Monologue | Seed voice identity; no announcer tone | **Not judged.** Matching transcripts establish neither timbre nor delivery. |
| Monologue | Matte skin with pores | **Held.** All retain visible texture and natural facial detail. |
| Monologue | Locked close-up; whole head inside | **Partly.** Stable close-ups, but crown cropping, strongest in 13. |
| Two-shot | Only speaker’s lips move | **Partly, visually.** 21/23 show an attentive, closed-mouth listener; 22 removes him. Audio attribution not judged. |
| Two-shot | Distinct faces, no identity bleeding | **Held where visible.** All retain distinguishable characters; absence in 22 is a separate failure. |
| Two-shot | Static two-shot, S1 left/S2 right | **Partly.** 21/23 hold the arrangement; 22 fails it. |
| Two-shot | No opening flash/jump within 0.5 s | **Partly.** 21/23 held; 22 visibly cuts within that interval. |
| Two-shot | Line within window; closed-mouth ending | **Partly.** End frames close mouths where visible, but measured speech ends 5.38–5.49 s, after 3.900. |
| Reverse pair | Left/right positions across both clips | **Held.** All pairs retain S1 left and S2 right. |
| Reverse pair | Blurred foreground shoulder on named side | **Partly.** Correct sides throughout; foreground heads are larger and often sharper than the specified shoulder framing. |
| Reverse pair | Portrait identities across independent clips | **Held.** All six remain recognizably the reference characters. |
| Reverse pair | Only designated speaker talks | **Not judged audibly.** Visible mouth activity broadly supports the assignments; transcripts contain the intended lines. |
| Reverse pair | Normal reverse cut; no frozen portrait opening | **Held, with reservation.** All begin in scene; 31B’s near-camera eyeline is the least convincing reverse. |
| Walk and talk | Unbroken eight-second take; no restart | **Held.** All remain continuous in the inspected sequences. |
| Walk and talk | Small, slow tracking without excess sway | **Partly.** 41/42 visibly bob; 43 closes from medium toward close-up. Still usable direction. |
| Walk and talk | Lips follow line while walking | **Not judged for sync.** All visibly continue walking while articulating. |
| Walk and talk | Face and clothing identity through walk | **Held.** All preserve recognizable appearance. |
| Walk and talk | Head remains inside frame | **Held.** All retain the head through the walk. |
| Outburst | Shout rises approximately 7.6–10.2 dB above seed | **Partly supported by level measurements.** Against Chen’s −20.9 dB seed, track gains are +2.9/+5.6/+4.5 dB; none reaches that range. Vocal-only gain not judged. |
| Outburst | Same recognizable voice; no announcer tone | **Not judged.** No suitable voice-identity evidence. |
| Outburst | Push/shake only at slam, then settle | **Partly.** Movement accompanies confrontation, but 51 continues pushing later; the exact movement-and-settle pattern is not consistent across seeds. |
| Outburst | Both heads fully framed with headroom | **Partly.** Speaking faces remain readable; 51’s foreground head loses comfortable clearance during the push. |
| Outburst | No haze or grey wash | **Held.** All retain clear blacks, faces, and background detail. |
| Stand-up | Head never cropped during rise | **Failed.** All three cross the top edge during the rise. |
| Stand-up | Smooth upward/outward compensation, then stop; no cuts | **Partly.** Continuous reframing occurs, but it lags the actor; 62 also has noticeable cant. |
| Stand-up | Full stand rather than half-rise | **Held.** All visibly stand fully. |
| Stand-up | Line while standing; lips follow | **Held for standing; sync not judged.** Measured speech starts 3.31–3.50 s, when he is upright. |
| Stand-up | Other character stays seated left, without intrusion | **Held.** All preserve that blocking. |
| Reaction | Ninety-frame sampling takes 50–65 seconds | **Failed in this reproduction.** All measured 78.0 seconds, excluding wall overhead. |
| Reaction | Exclamation matches lips and finishes in window | **Failed timing; sync not judged.** Ends 3.34/3.42/3.37 s, after the 2.900 deadline. |
| Reaction | Held close-up; readable startle; no cut | **Held.** All deliver a recognizable reaction without a visible cut. |
| Reaction | Face identity and close-range skin texture | **Held.** All preserve facial identity and texture. |
| Fight | Zero arm/body interpenetration | **Partly supported.** No definite gross body fusion in inspected contacts; 81B’s glove/wrist junction remains insufficiently clear to certify “zero.” |
| Fight | Action starts immediately at 0.000 | **Failed.** All A clips open on the reference portrait before entering the fight. |
| Fight | Legs and footwork visible | **Failed as a continuous guarantee.** All six hide feet for substantial passages; isolated knees and kicks remain readable. |
| Fight | Separation at eight seconds; invisible join | **Held visually.** All A endings separate the fighters; exact A/B boundary frames match convincingly. |
| Fight | Hits align with timed impact sounds | **Not judged.** Track level and frame-difference measurements cannot establish synchronization. |
| Fight | Identities and left/right positions through both clips | **Partly.** Sides hold throughout; 81 has noticeable male face/coat appearance drift across A/B. |
| Dance | Solo dancer; no wax-figure bystander | **Held.** All remain solo. |
| Dance | Continuous motion for all 12.25 seconds | **Partly.** 91 has a portrait hold and cut; 92/93 delay their starts, then sustain the phrase. The final still pose is explicitly prompted. |
| Dance | Feet and full body remain visible | **Failed.** All crop important movement; 93 loses the upper body at the leap’s apex, 91/92 for longer passages. |
| Dance | Movement follows musical beat | **Not judged.** No beat-alignment measurement or listening. |
| Dance | Dancer identity through arc move | **Held where visible.** Recognizable face and performer throughout; 91’s dress silhouette changes after its opening. |
| Tea | Right pours; left stays flat and still | **Partly.** Correct pouring hand in all; 101 curls the resting left hand instead of keeping it flat. |
| Tea | Five separated fingers; no extra/fused digits | **Partly.** No definite extra digits observed, but gripping hands conceal fingers and 101’s resting fingers are curled. |
| Tea | Coherent pot, cup, and tea stream | **Held.** All show a readable pour into a stable cup without an obvious prop discontinuity. |
| Tea | Roles switch at 6.500; no mirror flip | **Partly.** Correct left-hand cup pickup near the intended beat in all; right hand does not consistently become flat and still. No flip observed. |
| Tea | Static framing contains head and hands | **Partly.** 101/102 retain useful framing; 103 moves close enough to cut off the upper face. |
| Four-segment | Segment 1 opens cleanly on medium two-shot | **Partly.** 2201/4201 do; 3201 opens and remains on Lin alone. No comparable opening flash in those first segments. |
| Four-segment | One medium two-shot across all four segments | **Failed.** All change composition; 3201 introduces solo and over-the-shoulder coverage, 4201 pushes to Chen alone and resets the setup, 2201 jumps and later crops Chen. |
| Four-segment | No haze/grey wash in segments 3–4 | **Held.** All retain usable contrast and detail. |
| Four-segment | Female approximately +8 dB; male approximately +7.6 dB | **Partly.** Female +1.6/+3.8/+3.5; male +4.8/+7.5/+6.9 dB. Male gains approach the claim in two runs; female gains do not. |
| Four-segment | Same character voice across segments | **Not judged.** Transcript identity is not voice identity. |
| Four-segment | Exact level, 90-degree profile through segment 3’s end | **Failed as rendered; reproduction-confounded.** All show head-angle/tilt variation; none demonstrates the strict lock. |
| Four-segment | Both heads have headroom during segment 4 slam | **Partly.** 2201 clearly crops Chen’s crown; 3201/4201 contain the speaking head more successfully. |
| Four-segment | Each line once, inside window, closed-mouth ending | **Partly.** All twelve blind transcripts contain the intended line without repetition; timing and closing holds fail. Lin’s mouth remains visibly open at all three segment-3 endpoints. |
| Four-segment | Approximately 12.5-minute render for twenty seconds | **Held approximately.** Measured render 12.75/12.85/12.75 minutes for about 20.04 seconds. This excludes omitted finishing passes. |

The repeated headroom, immediate-start, framing, and deadline failures make categorical promises look overstated for this first-pass workflow. Two claims also conflict with the supplied prompts: the fight requests “knee-up” framing while promising visible footwork, and the dance explicitly requests a final still pose while claiming no holds.

The reproduction limitations matter most for the four-segment scene's profile lock: strengths 0.90/0.95 were lost, anchoring became full-weight, and the node no longer rewrote the sampler latent. Frame 107’s incompatibility with the stated 17-frame guide rule was retained from the author’s graph. Different voice-seed slices and locally generated action references also weaken direct voice/appearance comparisons; omitted upscale and face refinement limit conclusions about the author’s finished output. The reaction-speed miss establishes this run’s performance, not a universal hardware-independent limit.

These are the distinct observed failure modes; counts overlap:

| Defect | Clips affected | Where and likely association |
|---|---:|---|
| Reference portrait used as an opening | **5** | two-shot 22; all three fight A clips; dance91. Strong association with reference conditioning. |
| Unrequested hard cut or abrupt setup cut | **9** | Those five, plus four-segment 2201/3, 3201/2, 3201/3 at its incoming boundary, 4201/3. Portrait openings are removable; some four-segment cuts resemble editing, others disrupt continuity. |
| Required second character absent for part/all of shot | **7** | two-shot 22; three fight A openings; four-segment 3201/1 and 4201/2–3. Reference openings and composition drift. |
| Damaging head/upper-body clipping | **8** | Three stand-ups, three dances, tea103, four-segment 2201/4. Strong association with vertical movement or tightening framing; ordinary close-up crown crops excluded. |
| Footwork hidden | **6** | All fight clips. Scene/prompt framing issue, not merely a long-clip failure. |
| Appearance/costume continuity warning | **3 involved** | Fight81 A/B: male face/coat appearance; dance91: dress silhouette after opening. Reference-sensitive; no definite character swap. |
| Stiff, unconvincing action response | **1** | Fight82B: prolonged forward-facing, nearly inert opponent during the supposed trap. Seed-specific performance failure. |
| Unwanted generated subtitles | **1** | Outburst52. Apparently seed-specific. |
| Prescribed resting-hand pose not maintained | **3** | All tea clips at the final hand-role change; 101 also curls the left hand during pouring. Fine-action instruction failure. |
| Measured speech-window violation | **34 of 36 dialogue clips** | All except walk41/43, using word timestamps and accounting for the 22-frame context trim in segments 2–4 of the four-segment scene. Includes 32 late endings; not a lip-sync diagnosis. |
| Clearly absent prescribed closed-mouth tail | **At least 6** | All reactions and all segment-3 endings of the four-segment scene. The reaction endings remain editorially usable. |
| Exact level-profile lock absent | **3** | All segment-3 clips of the four-segment scene. Directly confounded by the altered end-frame lock port. |

I found **no confirmed split-screen/diptych [corrected: see the note at the top], cloned character, left/right mirror flip, gross extra limb, or pervasive haze wash**. The fight’s high frame-difference counts are not equivalent to that many cuts. Corridor brightness changes follow movement through overhead lighting; I would not label them confirmed flicker artifacts.

Watch these first; “best” does not mean every claim held:

| Scene | First clip |
|---|---|
| Monologue | **12/clip1** — balanced close-up and restrained performance. |
| Two-shot | **21/clip1** — clearest sustained two-shot. |
| Reverse pair | **32/A, then B** — most straightforward reverse pair. |
| Walk and talk | **42/clip1** — readable walking performance with useful framing. |
| Outburst | **51/clip1** — strongest visible escalation and purposeful push-in. |
| Stand-up | **63/clip1** — clearest overall blocking despite the rise crop. |
| Reaction | **72/clip1** — readable, comparatively restrained surprise. |
| Fight | **83/stitched** — best complete exchange after trimming the portrait opening. |
| Dance | **93/clip1** — strongest full-body coverage until the leap. |
| Tea | **102/clip1** — clearest balance of face, hands, and props. |
| Four-segment | **2201/stitched** — closest overall staging continuity, with the stated jump and crop. |

The three clips most worth human adjudication are **fight81B**—whether the wrist contact reads as a real grip at playback speed, provisionally fixable; **over-the-shoulder 31B**—whether its eyeline sells the reverse, provisionally usable; and **four-segment 3201 segment 3**, preferably with the preceding segment—whether the setup change reads as acceptable coverage or a continuity glitch, provisionally fixable.

Three fixed seeds give a small descriptive sample, not dependable success probabilities. Here, 3/3 means “worked in these three,” and 0/3 means “failed in these three”; neither establishes certainty for another seed, cast, prompt, or setting. Shared references and chained clips further limit independence, and these durations cannot isolate a clip-length effect from scene difficulty. The rates describe visual editorial usability of this reproduction, with voice quality and synchronization still unjudged.